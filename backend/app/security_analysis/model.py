"""Independent nature and origin-layer estimators with explicit abstention."""

from dataclasses import asdict, dataclass
from collections import Counter
import math
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier

from .features import FEATURE_NAMES, FEATURE_VERSION


NATURE_CLASSES = ("normal", "fault", "attack")
ORIGIN_CLASSES = ("sensor", "communication", "controller", "firmware_config", "actuator_inverter")
NATURE_DISPLAY = {"normal": "Normal", "fault": "Accidental fault", "attack": "Cyber attack"}
ORIGIN_DISPLAY = {"sensor": "Sensor", "communication": "Communication",
                  "controller": "Controller", "firmware_config": "Firmware-Config",
                  "actuator_inverter": "Actuator-Inverter"}


@dataclass(frozen=True)
class AbstentionPolicy:
    nature_minimum: float = 0.58
    origin_minimum: float = 0.52
    margin_minimum: float = 0.08

    def __post_init__(self):
        if any(not math.isfinite(value) or not 0 < value <= 1
               for value in (self.nature_minimum, self.origin_minimum)):
            raise ValueError("confidence thresholds must be in (0, 1]")
        if not math.isfinite(self.margin_minimum) or not 0 <= self.margin_minimum <= 1:
            raise ValueError("margin_minimum must be in [0, 1]")


class AttributionModels:
    def __init__(self, policy=None):
        self.policy = policy or AbstentionPolicy()
        self.nature_model = None
        self.origin_model = None
        self.metadata = {}

    @staticmethod
    def _validate_samples(samples):
        if not samples:
            raise ValueError("Training samples are required")
        ids, seeds = set(), set()
        for item in samples:
            if item["run_id"] in ids or item["seed"] in seeds:
                raise ValueError("Training samples must contain one window per unique run and seed")
            ids.add(item["run_id"])
            seeds.add(item["seed"])
            if tuple(item["features"]) != FEATURE_NAMES:
                raise ValueError("Feature schema mismatch")
        return ids, seeds

    def fit(self, samples, *, seed=42):
        ids, seeds = self._validate_samples(samples)
        nature = np.asarray([item["nature"] for item in samples])
        known = [item for item in samples if item["nature"] != "normal" and item["origin_layer"]]
        origins = np.asarray([item["origin_layer"] for item in known])
        if set(nature) != set(NATURE_CLASSES):
            raise ValueError("Nature training data must include normal, fault, and attack runs")
        if set(origins) != set(ORIGIN_CLASSES):
            raise ValueError("Origin training data must include all five known origin layers")
        values = np.asarray([[item["features"][name] for name in FEATURE_NAMES]
                             for item in samples], dtype=float)
        origin_values = np.asarray([[item["features"][name] for name in FEATURE_NAMES]
                                    for item in known], dtype=float)
        if not np.isfinite(values).all() or not np.isfinite(origin_values).all():
            raise ValueError("Features must be finite")
        self.nature_model = RandomForestClassifier(n_estimators=240, max_depth=14,
            min_samples_leaf=2, class_weight="balanced_subsample", random_state=seed, n_jobs=1)
        self.origin_model = RandomForestClassifier(n_estimators=240, max_depth=14,
            min_samples_leaf=2, class_weight="balanced_subsample", random_state=seed + 1, n_jobs=1)
        self.nature_model.fit(values, nature)
        self.origin_model.fit(origin_values, origins)
        self.metadata = {"feature_version": FEATURE_VERSION,
                         "feature_names": list(FEATURE_NAMES),
                         "sklearn_version": sklearn.__version__, "random_seed": seed,
                         "training_run_ids": sorted(ids), "training_seeds": sorted(seeds),
                         "training_sample_count": len(samples),
                         "training_nature_counts": dict(Counter(item["nature"] for item in samples)),
                         "training_origin_counts": dict(Counter(item["origin_layer"] for item in known)),
                         "nature_classes": list(NATURE_CLASSES),
                         "origin_classes": list(ORIGIN_CLASSES),
                         "policy": asdict(self.policy),
                         "confidence_kind": "uncalibrated_random_forest_probability",
                         "calibration": "Not calibrated; confidence values are model scores, not calibrated probabilities."}
        return self

    def predict_features(self, features):
        if self.nature_model is None or self.origin_model is None:
            return {"available": False, "nature": "not available", "nature_confidence": None,
                    "origin": "not available", "origin_confidence": None,
                    "origin_candidates": [], "confidence_kind": "not available"}
        if tuple(features) != FEATURE_NAMES:
            raise ValueError("Feature schema mismatch")
        vector = np.asarray([[features[name] for name in FEATURE_NAMES]], dtype=float)
        if not np.isfinite(vector).all():
            raise ValueError("Features must be finite")
        nature_scores = self.nature_model.predict_proba(vector)[0]
        nature_ranked = sorted(zip(self.nature_model.classes_, nature_scores),
                               key=lambda pair: (-pair[1], str(pair[0])))
        nature_top, nature_second = nature_ranked[0], nature_ranked[1]
        nature_score = float(nature_top[1])
        nature_internal = str(nature_top[0])
        nature_label = NATURE_DISPLAY[nature_internal]
        if (nature_score < self.policy.nature_minimum or
                nature_score - float(nature_second[1]) < self.policy.margin_minimum):
            nature_label = "Undetermined"
        origin_scores = self.origin_model.predict_proba(vector)[0]
        origin_ranked = sorted(zip(self.origin_model.classes_, origin_scores),
                               key=lambda pair: (-pair[1], str(pair[0])))
        candidates = [{"layer": ORIGIN_DISPLAY[str(name)], "confidence": float(score)}
                      for name, score in origin_ranked]
        origin_top, origin_second = origin_ranked[0], origin_ranked[1]
        origin_score = float(origin_top[1])
        origin_internal = str(origin_top[0])
        origin_label = ORIGIN_DISPLAY[origin_internal]
        if (nature_internal == "normal" or nature_label == "Undetermined" or
                origin_score < self.policy.origin_minimum or
                origin_score - float(origin_second[1]) < self.policy.margin_minimum):
            origin_label = "Unknown"
        return {"available": True, "nature": nature_label,
                "nature_confidence": nature_score,
                "nature_candidates": [{"nature": str(name), "confidence": float(score)}
                                      for name, score in nature_ranked],
                "origin": origin_label, "origin_confidence": origin_score if origin_label != "Unknown" else None,
                "origin_candidates": candidates,
                "confidence_kind": self.metadata.get("confidence_kind",
                    "uncalibrated_random_forest_probability"),
                "indicators_are_not_proof": True}

    def predict_sample(self, sample):
        result = self.predict_features(sample["features"])
        if not result["available"]:
            return result
        from .attribution import build_attribution
        result["evidence"] = build_attribution(sample["telemetry_window"], result)
        return result

    def save(self, path):
        if self.nature_model is None or self.origin_model is None:
            raise RuntimeError("Cannot save untrained models")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"nature_model": self.nature_model, "origin_model": self.origin_model,
                     "policy": self.policy, "metadata": self.metadata}, path)

    @classmethod
    def load(cls, path):
        artifact = joblib.load(path)
        metadata = artifact["metadata"]
        if (metadata["feature_version"] != FEATURE_VERSION or
                metadata["feature_names"] != list(FEATURE_NAMES) or
                metadata["sklearn_version"] != sklearn.__version__):
            raise ValueError("Feature schema or scikit-learn version mismatch; retrain")
        model = cls(artifact["policy"])
        model.nature_model = artifact["nature_model"]
        model.origin_model = artifact["origin_model"]
        model.metadata = metadata
        return model

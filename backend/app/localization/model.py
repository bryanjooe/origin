"""Random Forest source hypotheses with explicit abstention and uncertainty."""
from dataclasses import asdict, dataclass
import math
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier

from .dataset import CLASSES, DISPLAY_NAMES, UNKNOWN, training_arrays
from .features import FEATURE_NAMES, FEATURE_VERSION, LocalizationObservation


@dataclass(frozen=True)
class ConfidencePolicy:
    minimum_confidence: float = 0.65
    minimum_margin: float = 0.15

    def __post_init__(self):
        if not math.isfinite(self.minimum_confidence) or not 0 < self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be in (0, 1]")
        if not math.isfinite(self.minimum_margin) or not 0 <= self.minimum_margin <= 1:
            raise ValueError("minimum_margin must be in [0, 1]")


class SourceLocalizer:
    def __init__(self, policy: ConfidencePolicy | None = None):
        self.policy = policy or ConfidencePolicy()
        self.classifier = None
        self.metadata = {}

    def fit(self, runs, *, seed=42):
        values, targets, table = training_arrays(runs)
        classifier = RandomForestClassifier(n_estimators=200, max_depth=16, min_samples_leaf=4,
                                            class_weight="balanced_subsample", random_state=seed, n_jobs=1)
        classifier.fit(values, targets)
        self.classifier = classifier
        self.metadata = {"feature_version": FEATURE_VERSION, "feature_names": list(FEATURE_NAMES),
                         "sklearn_version": sklearn.__version__, "random_seed": seed,
                         "training_runs": [run.manifest() for run in runs], "training_rows": len(table),
                         "class_counts": {key: int(value) for key, value in table["target"].value_counts().items()},
                         "policy": asdict(self.policy), "confidence_kind": "uncalibrated_random_forest_probability",
                         "classes": list(CLASSES)}
        return self

    def predict(self, observations: list[LocalizationObservation], policy: ConfidencePolicy | None = None):
        if self.classifier is None:
            raise RuntimeError("Source model unavailable: train or load a model first")
        if not observations:
            return []
        policy = policy or self.policy
        values = np.asarray([observation.vector() for observation in observations], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("Features must be finite")
        probabilities = self.classifier.predict_proba(values)
        results = []
        for observation, scores in zip(observations, probabilities):
            candidates = sorted([{"source": str(source), "label": DISPLAY_NAMES[str(source)],
                                  "confidence": float(score)}
                                 for source, score in zip(self.classifier.classes_, scores)],
                                key=lambda item: (-item["confidence"], item["source"]))
            top, second = candidates[:2]
            margin = top["confidence"] - second["confidence"]
            reasons = []
            if observation.features["soc_estimate_available"] < 0.5:
                reasons.append("State estimate unavailable: initialize telemetry from a known simulation reset")
            if top["confidence"] < policy.minimum_confidence:
                reasons.append("Top candidate confidence is below the configured threshold")
            if margin < policy.minimum_margin:
                reasons.append("Several candidate sources have similar classifier scores")
            predicted = UNKNOWN if reasons else top["source"]
            results.append({"tick": observation.tick, "elapsed_seconds": observation.elapsed_seconds,
                            "predicted_source": predicted, "label": DISPLAY_NAMES[predicted],
                            "confidence": top["confidence"] if not reasons else None,
                            "top_candidate": top, "alternatives": candidates[1:3], "candidates": candidates,
                            "candidate_margin": margin, "abstention_reasons": reasons,
                            "confidence_kind": "uncalibrated_random_forest_probability",
                            "supporting_observations": observation.evidence,
                            "observed_features": dict(observation.features),
                            "interpretation": "A classifier hypothesis, not a proven root cause"})
        return results

    def save(self, path: str | Path):
        if self.classifier is None:
            raise RuntimeError("Cannot save an untrained source model")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"classifier": self.classifier, "policy": self.policy, "metadata": self.metadata}, path)

    @classmethod
    def load(cls, path: str | Path):
        # Load only trusted, locally generated Joblib artifacts.
        artifact = joblib.load(path)
        metadata = artifact["metadata"]
        if (metadata["feature_version"] != FEATURE_VERSION or metadata["feature_names"] != list(FEATURE_NAMES)
                or metadata["sklearn_version"] != sklearn.__version__ or metadata["classes"] != list(CLASSES)):
            raise ValueError("Source model schema or scikit-learn version mismatch; retrain")
        model = cls(artifact["policy"])
        model.classifier, model.metadata = artifact["classifier"], metadata
        return model

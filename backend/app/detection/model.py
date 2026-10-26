"""Normal-baseline Isolation Forest, with separately reported residual rules."""
from dataclasses import dataclass
from pathlib import Path
import math

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .dataset import ScenarioRun, feature_table, validate_partitions
from .features import FEATURE_NAMES, FEATURE_VERSION, Observation


@dataclass(frozen=True)
class Thresholds:
    warning: float
    critical: float

    def __post_init__(self):
        if not (math.isfinite(self.warning) and math.isfinite(self.critical)
                and 0 < self.warning < self.critical <= 1):
            raise ValueError("Require 0 < warning < critical <= 1")


class AnomalyDetector:
    def __init__(self):
        self.pipeline = None
        self.thresholds = None
        self.metadata = {}

    def fit(self, train: list[ScenarioRun], calibration: list[ScenarioRun], *, seed=42,
            warning_quantile=0.99, critical_quantile=0.999):
        if not 0 < warning_quantile < critical_quantile < 1:
            raise ValueError("Require 0 < warning quantile < critical quantile < 1")
        validate_partitions(train, calibration)
        if not train or not calibration or any(run.fault is not None for run in [*train, *calibration]):
            raise ValueError("Training and calibration require normal-only complete runs")
        training = feature_table(train).loc[:, FEATURE_NAMES]
        calibrating = feature_table(calibration).loc[:, FEATURE_NAMES]
        if len(training) < 256 or len(calibrating) < 128:
            raise ValueError("Require at least 256 training and 128 calibration rows")
        pipeline = make_pipeline(StandardScaler(), IsolationForest(
            n_estimators=200, max_samples=512, contamination="auto", random_state=seed, n_jobs=1))
        pipeline.fit(training.to_numpy())
        scores = -pipeline.score_samples(calibrating.to_numpy())
        warning = float(np.quantile(scores, warning_quantile))
        critical = max(warning + 0.01, float(np.quantile(scores, critical_quantile)))
        self.pipeline = pipeline
        self.thresholds = Thresholds(warning, min(1.0, critical))
        self.metadata = {"feature_version": FEATURE_VERSION, "feature_names": list(FEATURE_NAMES),
                         "sklearn_version": sklearn.__version__, "random_seed": seed,
                         "training_runs": [run.manifest() for run in train],
                         "calibration_runs": [run.manifest() for run in calibration],
                         "training_rows": len(training), "calibration_rows": len(calibrating),
                         "warning_quantile": warning_quantile, "critical_quantile": critical_quantile}
        return self

    def predict(self, observations: list[Observation], thresholds: Thresholds | None = None):
        if self.pipeline is None or self.thresholds is None:
            raise RuntimeError("Anomaly model unavailable: train or load a model first")
        limits = thresholds or self.thresholds
        if not observations:
            return []
        vectors = np.asarray([observation.vector() for observation in observations], dtype=float)
        if not np.isfinite(vectors).all():
            raise ValueError("Features must be finite")
        scores = -self.pipeline.score_samples(vectors)
        results = []
        for observation, score in zip(observations, scores):
            ml_status = "critical" if score >= limits.critical else "warning" if score >= limits.warning else "normal"
            rules = observation.residual_checks
            results.append({"tick": observation.tick, "elapsed_seconds": observation.elapsed_seconds,
                            "anomaly_score": float(score), "ml_status": ml_status,
                            "warning_threshold": limits.warning, "critical_threshold": limits.critical,
                            "residual_checks": rules, "rule_status": "warning" if rules else "normal",
                            "combined_status": ml_status if ml_status != "normal" else "warning" if rules else "normal",
                            "affected_variables": [check["signal"] for check in rules],
                            "ml_explanation": "Outside calibrated normal score range" if ml_status != "normal"
                            else "Within calibrated normal score range"})
        return results

    def save(self, path: str | Path):
        if self.pipeline is None:
            raise RuntimeError("Cannot save an untrained model")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": self.pipeline, "thresholds": self.thresholds,
                     "metadata": self.metadata}, path)

    @classmethod
    def load(cls, path: str | Path):
        # Joblib is pickle-based: only load locally generated/trusted artifacts.
        artifact = joblib.load(path)
        metadata = artifact["metadata"]
        if (metadata["feature_version"] != FEATURE_VERSION
                or metadata["feature_names"] != list(FEATURE_NAMES)
                or metadata["sklearn_version"] != sklearn.__version__):
            raise ValueError("Model schema or scikit-learn version mismatch; retrain")
        model = cls()
        model.pipeline, model.thresholds, model.metadata = artifact["pipeline"], artifact["thresholds"], metadata
        return model

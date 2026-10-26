from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from app.detection import AnomalyDetector
from app.detection.dataset import fault_runs, normal_runs, simulate_run
from app.detection.evaluation import evaluate as evaluate_anomaly
from app.fault_injection import Fault
from app.localization import SourceLocalizer
from app.localization.dataset import partition_runs
from app.localization.evaluation import evaluate as evaluate_source


class ModelRegistry:
    def __init__(self, settings):
        self.detector = self.localizer = None
        self.errors, self.fingerprints, self.reports, self.report_errors = {}, {}, {}, {}
        for name, path, loader in (("anomaly", settings.anomaly_model, AnomalyDetector.load),
                                   ("source", settings.source_model, SourceLocalizer.load)):
            try:
                if path is None:
                    raise FileNotFoundError("Model path is not configured")
                path = Path(path)
                model = loader(path)
                if name == "anomaly":
                    self.detector = model
                else:
                    self.localizer = model
                self.fingerprints[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception as error:
                self.errors[name] = f"{type(error).__name__}: {error}"
                continue
            try:
                report_path = path.parent / "evaluation.json"
                if report_path.exists():
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                    expected = asdict(model.thresholds) if name == "anomaly" else asdict(model.policy)
                    if report.get("thresholds" if name == "anomaly" else "policy") == expected:
                        self.reports[name] = {"provenance": "saved report from artifact directory; not recomputed by server",
                                              "report": report}
                    else:
                        self.report_errors[name] = "Saved report thresholds/policy do not match the loaded artifact"
            except Exception as error:
                self.report_errors[name] = f"{type(error).__name__}: {error}"

    def availability(self):
        return {"anomaly": {"available": self.detector is not None, "error": self.errors.get("anomaly")},
                "source": {"available": self.localizer is not None, "error": self.errors.get("source")}}

    def evaluate(self, profile):
        reports = {}
        if self.detector is not None:
            if profile == "full":
                normal, faulty = normal_runs("test", 8), fault_runs()
            else:
                normal = normal_runs("test", 1, 360)
                modes = [("sensor", "bias"), ("communication", "delay"), ("controller", "wrong_dispatch"),
                         ("firmware", "discharge_limit"), ("inverter", "derate")]
                faulty = [simulate_run(f"api-quick-{kind}", 800000 + i, 240,
                                       Fault(kind, mode, 40, 120, 0.8), start_hour=16)
                          for i, (kind, mode) in enumerate(modes)]
            reports["anomaly"] = evaluate_anomaly(self.detector, normal, faulty)
        if self.localizer is not None:
            runs = partition_runs("test") if profile == "full" else partition_runs("test", repeats=1, normal_count=2, ticks=240)
            reports["source"] = evaluate_source(self.localizer, runs)
        return {name: {"provenance": "server recomputed held-out scenarios", "profile": profile, "report": report}
                for name, report in reports.items()}

"""Evaluate frozen thresholds; fault labels are used only after inference."""
import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from .dataset import ScenarioRun, validate_partitions
from .model import AnomalyDetector


def binary_metrics(truth, prediction):
    truth, prediction = np.asarray(truth, dtype=bool), np.asarray(prediction, dtype=bool)
    tp = int(np.sum(truth & prediction))
    fp = int(np.sum(~truth & prediction))
    tn = int(np.sum(~truth & ~prediction))
    fn = int(np.sum(truth & ~prediction))
    return {"true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None}


def evaluate(model: AnomalyDetector, normal: list[ScenarioRun], faulty: list[ScenarioRun]):
    if model.pipeline is None:
        raise RuntimeError("Anomaly model unavailable")
    validate_partitions(normal, faulty)
    if not normal or not faulty or any(run.fault for run in normal) or any(run.fault is None for run in faulty):
        raise ValueError("Evaluation requires normal runs and labeled fault runs")
    used = [*model.metadata["training_runs"], *model.metadata["calibration_runs"]]
    if any(run.run_id in {item["run_id"] for item in used} or run.seed in {item["seed"] for item in used}
           for run in [*normal, *faulty]):
        raise ValueError("Evaluation runs must be held out from training and calibration")
    truth, scores = [], []
    predictions = {"ml": [], "rules": [], "combined": []}
    per_run, by_mode = [], {}
    for run in [*normal, *faulty]:
        # No ground-truth object or labels are passed to the inference interface.
        results = model.predict(run.observations())
        active_results = [result for result in results if run.fault and run.fault.active(result["tick"])]
        if run.fault and not active_results:
            raise ValueError("Fault evaluation run has no active fault interval")
        # Dedicated normal runs supply negatives; active fault intervals supply positives.
        # Pre-fault/recovery rows are excluded to avoid labeling lingering effects normal.
        selected = active_results if run.fault else results
        label = run.fault is not None
        truth.extend([label] * len(selected))
        scores.extend(result["anomaly_score"] for result in selected)
        run_record = {"run_id": run.run_id, "seed": run.seed, "evaluated_rows": len(selected),
                      "kind": run.fault.kind.value if label else "normal",
                      "mode": run.fault.mode if label else None,
                      "severity": run.fault.severity if label else None}
        for method, key in (("ml", "ml_status"), ("rules", "rule_status"), ("combined", "combined_status")):
            flags = [result[key] != "normal" for result in selected]
            predictions[method].extend(flags)
            run_record[f"{method}_alert_fraction"] = sum(flags) / len(flags)
            if run.fault:
                first = next((result for result in selected if result[key] != "normal"), None)
                run_record[f"{method}_detection_delay_seconds"] = (
                    first["elapsed_seconds"] - run.fault.start_tick * run.config.tick_seconds if first else None)
        per_run.append(run_record)
        if run.fault:
            name = f"{run.fault.kind.value}/{run.fault.mode}"
            by_mode.setdefault(name, []).append(run_record)
    performance = {}
    for method, flags in predictions.items():
        metrics = binary_metrics(truth, flags)
        faults = [item for item in per_run if item["kind"] != "normal"]
        delays = [item[f"{method}_detection_delay_seconds"] for item in faults
                  if item[f"{method}_detection_delay_seconds"] is not None]
        metrics.update(detected_fault_runs=len(delays), total_fault_runs=len(faults),
                       mean_detection_delay_seconds=float(np.mean(delays)) if delays else None,
                       delay_denominator="detected runs only; missed runs have null delay")
        performance[method] = metrics
    performance["ml"].update(roc_auc=float(roc_auc_score(truth, scores)),
                              average_precision=float(average_precision_score(truth, scores)))
    summaries = []
    for name, records in sorted(by_mode.items()):
        for severity in sorted({r["severity"] for r in records}):
            group = [r for r in records if r["severity"] == severity]
            summaries.append({"fault_mode": name, "severity": severity, "runs": len(group),
                              **{f"{method}_active_tick_recall": float(np.mean([r[f"{method}_alert_fraction"] for r in group]))
                                 for method in predictions}})
    return {"evaluation_scope": "held-out synthetic simulation runs; anomaly detection only",
            "positive_definition": "active injected-fault ticks, including faults without observable symptoms",
            "negative_definition": "all ticks from separate no-fault runs; excludes fault-run recovery",
            "normal_run_count": len(normal), "fault_run_count": len(faulty),
            "normal_rows": sum(not value for value in truth), "fault_rows": sum(truth),
            "performance": performance, "by_mode_and_severity": summaries, "per_run": per_run,
            "evaluation_runs": [run.manifest() for run in [*normal, *faulty]]}

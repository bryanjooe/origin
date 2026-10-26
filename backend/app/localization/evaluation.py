"""Source classification metrics, including abstentions as errors in total accuracy."""
import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from app.detection.dataset import validate_partitions
from .dataset import CLASSES, UNKNOWN, selected_observations


def evaluate(model, runs):
    if model.classifier is None:
        raise RuntimeError("Source model unavailable")
    if not runs:
        raise ValueError("Evaluation requires complete held-out runs")
    validate_partitions(runs)
    training = model.metadata["training_runs"]
    if any(run.run_id in {item["run_id"] for item in training}
           or run.seed in {item["seed"] for item in training} for run in runs):
        raise ValueError("Evaluation runs must be held out from training")
    truth, predicted, raw = [], [], []
    per_run, by_group = [], {}
    for run in runs:
        observations, target = selected_observations(run)
        results = model.predict(observations)
        labels = [row["predicted_source"] for row in results]
        raw_labels = [row["top_candidate"]["source"] for row in results]
        truth.extend([target] * len(labels))
        predicted.extend(labels)
        raw.extend(raw_labels)
        accepted = [label for label in labels if label != UNKNOWN]
        first_correct = next((result for result in results if run.fault and result["predicted_source"] == target), None)
        record = {"run_id": run.run_id, "seed": run.seed, "target": target,
                  "mode": run.fault.mode if run.fault else None,
                  "severity": run.fault.severity if run.fault else None,
                  "evaluated_rows": len(labels), "correct_rows": labels.count(target),
                  "unknown_rows": labels.count(UNKNOWN), "accepted_rows": len(accepted),
                  "accuracy_including_unknown": labels.count(target) / len(labels),
                  "first_correct_localization_delay_seconds": (
                      first_correct["elapsed_seconds"] - run.fault.start_tick * run.config.tick_seconds
                      if first_correct else None)}
        per_run.append(record)
        if run.fault:
            by_group.setdefault((target, run.fault.mode, run.fault.severity), []).append(record)
    known_labels = list(CLASSES)
    matrix_labels = [*known_labels, UNKNOWN]
    accepted_mask = np.asarray(predicted) != UNKNOWN
    truth_array, prediction_array = np.asarray(truth), np.asarray(predicted)
    class_metrics = classification_report(truth, predicted, labels=known_labels, output_dict=True, zero_division=0)
    per_severity = []
    for (source, mode, severity), records in sorted(by_group.items()):
        total = sum(record["evaluated_rows"] for record in records)
        per_severity.append({"source": source, "mode": mode, "severity": severity, "runs": len(records),
                             "rows": total, "accuracy_including_unknown": sum(r["correct_rows"] for r in records) / total,
                             "unknown_rate": sum(r["unknown_rows"] for r in records) / total})
    delays = [record["first_correct_localization_delay_seconds"] for record in per_run
              if record["first_correct_localization_delay_seconds"] is not None]
    return {"scope": "held-out synthetic simulation source classification; not causal proof",
            "row_selection": "all dedicated normal-run ticks and active-fault ticks only; pre/post-fault rows excluded",
            "run_count": len(runs), "normal_runs": sum(run.fault is None for run in runs),
            "fault_runs": sum(run.fault is not None for run in runs), "rows": len(truth),
            "raw_accuracy": float(accuracy_score(truth, raw)),
            "accuracy_including_unknown": float(accuracy_score(truth, predicted)),
            "coverage": float(np.mean(accepted_mask)), "unknown_rate": float(np.mean(~accepted_mask)),
            "accepted_accuracy": float(np.mean(truth_array[accepted_mask] == prediction_array[accepted_mask])) if np.any(accepted_mask) else None,
            "per_class": {source: class_metrics[source] for source in CLASSES},
            "macro_f1": class_metrics["macro avg"]["f1-score"],
            "confusion_matrix": {"labels": matrix_labels, "rows": "true source", "columns": "predicted source",
                                 "counts": confusion_matrix(truth, predicted, labels=matrix_labels).tolist()},
            "unknown_handling": "abstention, not a trained fault class; counted as incorrect for known-source recall and total accuracy",
            "fault_runs_with_correct_localization": len(delays),
            "mean_first_correct_delay_seconds": float(np.mean(delays)) if delays else None,
            "delay_denominator": "fault runs with a correct accepted prediction only; misses have null delay",
            "per_mode_and_severity": per_severity, "per_run": per_run,
            "evaluation_runs": [run.manifest() for run in runs]}

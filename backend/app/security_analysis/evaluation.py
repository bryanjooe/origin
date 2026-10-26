"""Held-out run-level synthetic-simulation evaluation and baseline comparison."""

from collections import defaultdict

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix

from app.localization import LocalizationFeatureExtractor, SourceLocalizer
from .dataset import incident_sample
from .model import NATURE_CLASSES, NATURE_DISPLAY, ORIGIN_CLASSES, ORIGIN_DISPLAY


def _classification(truth, predicted, labels):
    if not truth:
        return {"count": 0, "confusion_matrix": {"labels": list(labels), "counts": []},
                "per_class": {}, "macro_f1": None}
    report = classification_report(truth, predicted, labels=list(labels), output_dict=True,
                                   zero_division=0)
    return {"count": len(truth),
            "confusion_matrix": {"labels": list(labels), "rows": "true", "columns": "predicted",
                                 "counts": confusion_matrix(truth, predicted, labels=list(labels)).tolist()},
            "per_class": {label: report[label] for label in labels},
            "macro_f1": report["macro avg"]["f1-score"]}


def evaluate(models, runs, detector, *, source_model_path=None):
    if models.nature_model is None or models.origin_model is None:
        raise RuntimeError("Stage B classifiers are not available")
    if not runs:
        raise ValueError("Evaluation requires held-out complete runs")
    training_ids, training_seeds = set(models.metadata["training_run_ids"]), set(models.metadata["training_seeds"])
    if any(run.run_id in training_ids or run.seed in training_seeds for run in runs):
        raise ValueError("Held-out runs overlap training runs or seeds")
    samples, missed = {}, []
    for run in runs:
        item = incident_sample(run, detector)
        if item is None:
            missed.append(run)
        else:
            samples[run.run_id] = item
    truth, predicted, origin_truth, origin_predicted = [], [], [], []
    by_stealth, by_attack, by_severity = (defaultdict(lambda: [0, 0, 0]) for _ in range(3))
    nature_rows = []
    for run in runs:
        sample = samples.get(run.run_id)
        output = (models.predict_features(sample["features"]) if sample else
                  {"nature": "Undetermined", "nature_confidence": None,
                   "origin": "Unknown", "origin_confidence": None})
        nature_true = NATURE_DISPLAY[run.nature]
        truth.append(nature_true)
        predicted.append(output["nature"])
        nature_rows.append((run, output, sample))
        if run.nature != "normal":
            origin_truth.append(ORIGIN_DISPLAY[run.origin_layer])
            origin_predicted.append(output["origin"])
        if run.nature == "attack":
            for table, key in ((by_stealth, run.stealth_level),
                               (by_attack, run.scenario_type),
                               (by_severity, run.severity)):
                table[key][1] += 1
                table[key][0] += output["nature"] == "Cyber attack"
                table[key][2] += sample is not None
    nature_report = _classification(truth, predicted,
                                    [*(NATURE_DISPLAY[label] for label in NATURE_CLASSES), "Undetermined"])
    origin_report = _classification(origin_truth, origin_predicted,
                                    [*(ORIGIN_DISPLAY[label] for label in ORIGIN_CLASSES), "Unknown"])
    binary_truth, binary_predicted = [], []
    fault_origin_truth, fault_origin_predicted = [], []
    for run, output, _sample in nature_rows:
        if run.nature in {"fault", "attack"}:
            binary_truth.append("Accidental fault" if run.nature == "fault" else "Cyber attack")
            binary_predicted.append(output["nature"])
        if run.nature == "fault":
            fault_origin_truth.append(ORIGIN_DISPLAY[run.origin_layer])
            fault_origin_predicted.append(output["origin"])
    nature_binary_report = _classification(binary_truth, binary_predicted,
                                           ["Accidental fault", "Cyber attack", "Undetermined"])
    new_fault_origin = _classification(fault_origin_truth, fault_origin_predicted,
                                       [*(ORIGIN_DISPLAY[label] for label in ORIGIN_CLASSES), "Unknown"])
    normal_runs = [run for run in runs if run.nature == "normal"]
    normal_sample_outputs = [(models.predict_features(samples[r.run_id]["features"])
                              if r.run_id in samples else {"nature": "Undetermined"})
                             for r in normal_runs]
    model_false_attack = sum(result["nature"] == "Cyber attack" for result in normal_sample_outputs)
    detector_false_positive = sum(run.run_id in samples for run in normal_runs)
    detected_attack = [samples[run.run_id]["detection_delay_ticks"] for run in runs
                       if run.nature == "attack" and run.run_id in samples]
    all_attack_runs = sum(run.nature == "attack" for run in runs)
    classification_delays = [samples[run.run_id]["inference_delay_ticks"] for run in runs
                              if run.nature == "attack" and run.run_id in samples]
    source_report = {"available": False, "reason": "Existing source model file not supplied or missing"}
    if source_model_path:
        try:
            source_model = SourceLocalizer.load(source_model_path)
            baseline_truth, baseline_truth_display, baseline_pred, baseline_accepted = [], [], [], []
            for run in runs:
                if run.nature != "fault" or run.run_id not in samples:
                    continue
                observations = LocalizationFeatureExtractor(run.config).transform(run.telemetry)
                result = source_model.predict([observations[samples[run.run_id]["inference_tick"]]])[0]
                baseline_truth.append({"firmware_config": "firmware", "actuator_inverter": "inverter"}.get(
                    run.origin_layer, run.origin_layer))
                baseline_truth_display.append(ORIGIN_DISPLAY[run.origin_layer])
                baseline_pred.append(result["predicted_source"])
                baseline_accepted.append(result["top_candidate"]["source"])
            source_to_layer = {"sensor": "Sensor", "communication": "Communication",
                               "controller": "Controller", "firmware": "Firmware-Config",
                               "inverter": "Actuator-Inverter", "unknown": "Unknown"}
            baseline_display = [source_to_layer.get(value, "Unknown") for value in baseline_pred]
            baseline_metrics = _classification(baseline_truth_display, baseline_display,
                [*(ORIGIN_DISPLAY[label] for label in ORIGIN_CLASSES), "Unknown"])
            source_report = {"available": True,
                "scope": "same held-out fault runs and same inference ticks; existing source-localization model",
                "macro_f1_including_unknown": baseline_metrics["macro_f1"],
                "per_class": baseline_metrics["per_class"],
                "confusion_matrix": baseline_metrics["confusion_matrix"],
                "accuracy_including_unknown": (sum(a == b for a, b in zip(baseline_truth, baseline_pred)) /
                                                len(baseline_truth)) if baseline_truth else None,
                "accepted_accuracy": (sum(a == b for a, b in zip(baseline_truth, baseline_pred)
                                          if b != "unknown") /
                                      sum(value != "unknown" for value in baseline_pred))
                                     if any(value != "unknown" for value in baseline_pred) else None,
                "raw_accuracy_before_abstention": (sum(a == b for a, b in zip(baseline_truth, baseline_accepted)) /
                                                    len(baseline_truth)) if baseline_truth else None,
                "coverage": (sum(value != "unknown" for value in baseline_pred) / len(baseline_pred))
                            if baseline_pred else None,
                "evaluated_fault_runs": len(baseline_truth)}
        except Exception as error:
            source_report = {"available": False, "reason": f"{type(error).__name__}: {error}"}
    return {"provenance": "synthetic simulation held-out complete runs",
            "window_rule": "first detector fire, then causal 20-tick window; no future telemetry",
            "held_out_run_count": len(runs), "detected_run_count": len(samples),
            "detector_miss_count": len(missed),
            "detector_coverage": len(samples) / len(runs),
            "nature": nature_report,
            "fault_vs_attack": nature_binary_report,
            "origin": origin_report,
            "fault_only_origin_comparison": {
                "new_origin_layer_classifier": new_fault_origin,
                "existing_source_classifier": source_report,
                "note": "Same held-out fault runs and inference times; new origin outputs are mapped to the existing five source families."},
            "normal_run_false_positive_rate": {
                "nature_classifier_attack_label": model_false_attack / len(normal_runs) if normal_runs else None,
                "detector_fire": detector_false_positive / len(normal_runs) if normal_runs else None,
                "normal_run_count": len(normal_runs)},
            "abstention_rate": {"nature": predicted.count("Undetermined") / len(predicted),
                                "origin": origin_predicted.count("Unknown") / len(origin_predicted)
                                if origin_predicted else None},
            "attack_detection_delay_ticks": {
                "mean_on_detected_attacks": float(np.mean(detected_attack)) if detected_attack else None,
                "missed_attack_rate": (all_attack_runs - len(detected_attack)) / all_attack_runs
                                      if all_attack_runs else None,
                "mean_inference_delay_including_post_fire_window": float(np.mean(classification_delays))
                                                                    if classification_delays else None},
            "nature_recall_by_stealth": {key: {"attack_label_rate": value[0] / value[1],
                                                  "detector_fire_rate": value[2] / value[1],
                                                  "run_count": value[1]}
                                         for key, value in sorted(by_stealth.items())},
            "nature_recall_by_attack_type": {key: {"attack_label_rate": value[0] / value[1],
                                                       "detector_fire_rate": value[2] / value[1],
                                                       "run_count": value[1]}
                                             for key, value in sorted(by_attack.items())},
            "nature_recall_by_severity": {str(key): {"attack_label_rate": value[0] / value[1],
                                                         "detector_fire_rate": value[2] / value[1],
                                                         "run_count": value[1]}
                                          for key, value in sorted(by_severity.items())},
            "existing_source_classifier_fault_comparison": source_report,
            "missed_detection_run_ids": [run.run_id for run in missed],
            "row_level_results": [{"run_id": run.run_id, "nature_truth": run.nature,
                                   "nature_prediction": result["nature"],
                                   "origin_truth": run.origin_layer,
                                   "origin_prediction": result["origin"],
                                   "scenario_type": run.scenario_type,
                                   "stealth_level": run.stealth_level,
                                   "severity": run.severity,
                                   "detector_fire_tick": sample["detector_fire_tick"] if sample else None,
                                   "inference_tick": sample["inference_tick"] if sample else None}
                                  for run, result, sample in nature_rows]}

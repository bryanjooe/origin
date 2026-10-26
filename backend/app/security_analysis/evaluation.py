"""Held-out run-level synthetic-simulation evaluation and baseline comparison."""

from collections import defaultdict

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.inspection import permutation_importance

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


def unalerted_run_output():
    """A trained detector with no alert contributes the operational Normal state."""
    return {"nature": "Normal", "nature_confidence": None,
            "origin": "Unknown", "origin_confidence": None}


def _calibration_metrics(model, samples, classes):
    if not samples:
        return {"brier_score": None, "expected_calibration_error_10_bins": None, "count": 0}
    y = [item["nature"] for item in samples]
    x = np.asarray([[item["features"][name] for name in model.metadata["feature_names"]]
                    for item in samples], dtype=float)
    probabilities = model.nature_model.predict_proba(x)
    ordered = list(model.nature_model.classes_)
    indices = [ordered.index(label) for label in classes]
    p = probabilities[:, indices]
    one_hot = np.asarray([[int(label == actual) for label in classes] for actual in y], dtype=float)
    brier = float(np.mean(np.sum((p - one_hot) ** 2, axis=1)))
    confidence = p.max(axis=1)
    correct = np.asarray([classes[int(index)] == actual for index, actual in zip(p.argmax(axis=1), y)])
    ece = 0.0
    for lower in np.linspace(0, 0.9, 10):
        mask = (confidence >= lower) & (confidence < lower + 0.1)
        if mask.any():
            ece += float(mask.mean() * abs(confidence[mask].mean() - correct[mask].mean()))
    return {"brier_score": brier, "expected_calibration_error_10_bins": float(ece),
            "count": len(samples), "method": "held-out run-level reliability; lower is better"}


def evaluate(models, runs, detector, *, source_model_path=None, alert_policy=None,
             sample_builder=None, compute_importance=True):
    if models.nature_model is None or models.origin_model is None:
        raise RuntimeError("Stage B classifiers are not available")
    if not runs:
        raise ValueError("Evaluation requires held-out complete runs")
    training_ids, training_seeds = set(models.metadata["training_run_ids"]), set(models.metadata["training_seeds"])
    if any(run.run_id in training_ids or run.seed in training_seeds for run in runs):
        raise ValueError("Held-out runs overlap training runs or seeds")
    sampler = sample_builder or incident_sample
    samples, missed = {}, []
    for run in runs:
        item = sampler(run, detector, alert_policy)
        if item is None:
            missed.append(run)
        else:
            samples[run.run_id] = item
    truth, predicted, origin_truth, origin_predicted = [], [], [], []
    by_stealth, by_attack, by_severity = (defaultdict(lambda: [0, 0, 0]) for _ in range(3))
    nature_rows = []
    for run in runs:
        sample = samples.get(run.run_id)
        output = models.predict_features(sample["features"]) if sample else unalerted_run_output()
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
    stealth_importance = {}
    run_by_id = {run.run_id: run for run in runs}
    for level in sorted({run.stealth_level for run in runs
                         if compute_importance and run.nature == "attack" and run.stealth_level}):
        subset = [item for run_id, item in samples.items()
                  if (run_by_id[run_id].nature == "fault" or
                      (run_by_id[run_id].nature == "attack" and run_by_id[run_id].stealth_level == level))]
        if len(subset) < 8 or {item["nature"] for item in subset} != {"fault", "attack"}:
            stealth_importance[level] = []
            continue
        x = np.asarray([[item["features"][feature] for feature in models.metadata["feature_names"]]
                        for item in subset])
        y = np.asarray([item["nature"] for item in subset])
        result = permutation_importance(models.nature_model, x, y, scoring="f1_macro",
            n_repeats=4, random_state=42, n_jobs=1)
        names = models.metadata["feature_names"]
        stealth_importance[level] = [{"feature": names[index], "importance": float(value)}
            for index, value in sorted(enumerate(result.importances_mean),
                                       key=lambda pair: (-pair[1], pair[0]))]
    return {"provenance": "synthetic simulation held-out complete runs",
            "window_rule": "first detector fire, then causal 20-tick window; no future telemetry",
            "held_out_run_count": len(runs), "detected_run_count": len(samples),
            "detector_miss_count": len(missed),
            "detector_coverage": len(samples) / len(runs),
            "alert_policy": (vars(alert_policy) if alert_policy else {"mode": "legacy any warning or residual"}),
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
            "nature_probability_calibration": _calibration_metrics(models, list(samples.values()),
                                                                      list(NATURE_CLASSES)),
            "nature_feature_importance_by_stealth": stealth_importance,
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

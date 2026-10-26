"""Build reproducible Stage B dataset and held-out evaluation artifacts."""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.inspection import permutation_importance
from sklearn.metrics import f1_score

from app.detection import AnomalyDetector, FeatureExtractor
from .audit import summarize_telemetry
from .dataset import (calibrate_alert_policy, feature_frame, generate_runs,
                      incident_sample, split_runs)
from .evaluation import evaluate
from .features import FEATURE_NAMES, FEATURE_VERSION
from .model import AttributionModels, NATURE_DISPLAY


def main():
    parser = argparse.ArgumentParser(description="Train/evaluate synthetic Origin Stage B classifiers")
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--ticks", type=int, default=240)
    parser.add_argument("--seed", type=int, default=72100)
    parser.add_argument("--output-dir", default="outputs/stage5")
    parser.add_argument("--anomaly-model", default="outputs/stage2/anomaly.joblib")
    parser.add_argument("--source-model", default="outputs/stage3/source_classifier.joblib")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    detector_path = Path(args.anomaly_model)
    detector = AnomalyDetector.load(detector_path)
    runs = generate_runs(repeats=args.repeats, ticks=args.ticks, seed=args.seed)
    train_runs, test_runs = split_runs(runs, seed=args.seed)
    general_train_runs, general_test_runs = split_runs(runs, seed=args.seed + 1,
                                                        held_out_stealth="stealthy")

    def evaluate_split(name, split_train, split_test):
        model_fit_runs, validation_runs = split_runs(split_train, test_fraction=0.2,
                                                       seed=args.seed + (1 if name == "held_out" else 2))
        policy, calibration = calibrate_alert_policy(validation_runs, detector)
        fitted_samples = [item for run in model_fit_runs
                          if (item := incident_sample(run, detector, policy)) is not None]
        validation_samples = [item for run in validation_runs
                              if (item := incident_sample(run, detector, policy)) is not None]
        if not fitted_samples or not validation_samples:
            raise RuntimeError("Alert gate left too few windows for model fitting or validation")

        validation_by_id = {item["run_id"]: item for item in validation_samples}

        def score(candidate):
            truth, predicted = [], []
            for run in validation_runs:
                sample = validation_by_id.get(run.run_id)
                result = candidate.predict_features(sample["features"]) if sample else {"nature": "Normal"}
                truth.append(NATURE_DISPLAY[run.nature])
                predicted.append(result["nature"])
            return float(f1_score(truth, predicted,
                labels=["Normal", "Accidental fault", "Cyber attack", "Undetermined"],
                average="macro", zero_division=0))

        candidates, validation_scores = {}, {}
        for family in ("random_forest", "gradient_boosting"):
            candidate = AttributionModels().fit(fitted_samples, seed=args.seed, algorithm=family)
            candidates[family] = candidate
            validation_scores[family] = score(candidate)
        selected = max(validation_scores, key=lambda family: (validation_scores[family],
                                                               family == "random_forest"))
        selected_model = AttributionModels().fit(fitted_samples, seed=args.seed,
            algorithm=selected, calibration_samples=validation_samples)
        report = evaluate(selected_model, split_test, detector,
            source_model_path=args.source_model if Path(args.source_model).exists() else None,
            alert_policy=policy)
        report["training_run_count"] = len(model_fit_runs)
        report["training_detected_window_count"] = len(fitted_samples)
        report["validation_run_count"] = len(validation_runs)
        report["validation_detected_window_count"] = len(validation_samples)
        report["validation_alert_calibration"] = calibration
        report["legacy_validation_alert_rate"] = {
            nature: sum(incident_sample(run, detector) is not None for run in validation_runs
                        if run.nature == nature) / max(1, sum(run.nature == nature for run in validation_runs))
            for nature in ("normal", "fault", "attack")}
        report["new_validation_alert_rate"] = {
            nature: sum(incident_sample(run, detector, policy) is not None for run in validation_runs
                        if run.nature == nature) / max(1, sum(run.nature == nature for run in validation_runs))
            for nature in ("normal", "fault", "attack")}
        normal_ml_alerts, normal_rule_alerts, normal_rule_signals, first_alert_ticks = 0, 0, {}, []
        for run in validation_runs:
            if run.nature != "normal":
                continue
            statuses = detector.predict(FeatureExtractor(run.config).transform(run.telemetry))
            ml_hits = [row for row in statuses if row["ml_status"] != "normal"]
            rule_hits = [row for row in statuses if row["residual_checks"]]
            normal_ml_alerts += bool(ml_hits)
            normal_rule_alerts += bool(rule_hits)
            first = next((row["tick"] for row in statuses
                          if row["combined_status"] != "normal"), None)
            if first is not None:
                first_alert_ticks.append(first)
            for row in rule_hits:
                for check in row["residual_checks"]:
                    normal_rule_signals[check["signal"]] = normal_rule_signals.get(check["signal"], 0) + 1
        normal_count = max(1, sum(run.nature == "normal" for run in validation_runs))
        report["legacy_normal_alert_diagnostics"] = {
            "validation_normal_run_count": normal_count,
            "ml_score_alert_runs": normal_ml_alerts,
            "ml_score_alert_run_rate": normal_ml_alerts / normal_count,
            "residual_rule_alert_runs": normal_rule_alerts,
            "residual_rule_alert_run_rate": normal_rule_alerts / normal_count,
            "residual_rule_signal_counts": normal_rule_signals,
            "first_legacy_alert_median_tick": (float(np.median(first_alert_ticks))
                                                if first_alert_ticks else None),
            "selection_data_only": True}
        report["model_selection"] = {"validation_macro_f1": validation_scores,
                                      "selected_by": "validation nature macro-F1",
                                      "selected": selected}
        report["feature_importance"] = selected_model.metadata["feature_importance"]
        x = np.asarray([[item["features"][feature] for feature in FEATURE_NAMES]
                        for item in validation_samples])
        y = np.asarray([item["nature"] for item in validation_samples])
        importance = permutation_importance(selected_model.nature_model, x, y,
            scoring="f1_macro", n_repeats=4, random_state=args.seed, n_jobs=1)
        report["feature_importance"] = [{"feature": FEATURE_NAMES[index], "importance": float(value)}
            for index, value in sorted(enumerate(importance.importances_mean),
                                       key=lambda pair: (-pair[1], pair[0]))]
        selected_model.metadata["permutation_feature_importance"] = report["feature_importance"]
        selected_model.save(output / f"{name}_fault_attack_origin.joblib")
        report["held_out_stealth_level"] = "stealthy" if name == "stealth_generalization" else None
        (output / f"{name}_evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report, selected_model, policy

    regular_report, model, policy = evaluate_split("held_out", train_runs, test_runs)
    general_report, _, _ = evaluate_split("stealth_generalization", general_train_runs, general_test_runs)
    all_samples = [item for run in runs
                   if (item := incident_sample(run, detector, policy)) is not None]
    feature_frame(all_samples).to_csv(output / "incident_features.csv", index=False)
    class_counts = dict(Counter(run.nature for run in runs))
    metadata = {"provenance": "synthetic simulations only",
                "generator_seed": args.seed,
                "configuration": {"repeats_per_cell": args.repeats, "ticks_per_run": args.ticks,
                    "severity_levels": [0.25, 0.6, 1.0],
                    "stealth_levels": ["naive", "moderate", "stealthy"],
                    "fault_modes": "all modes in backend/app/fault_injection/engine.py",
                    "attack_types": "all AttackType values, including multi_stage",
                    "anomaly_model": str(detector_path),
                    "window_rule": "first gated alert then causal window ending no later than inference tick",
                    "split_unit": "complete run; unique run IDs and seeds",
                    "alert_threshold_calibration": "training-derived validation run maxima only"},
                "feature_version": FEATURE_VERSION, "feature_names": list(FEATURE_NAMES),
                "run_count": len(runs), "class_run_counts": class_counts,
                "detected_window_count": len(all_samples), "detector_miss_count": len(runs)-len(all_samples),
                "run_manifests": [run.manifest() for run in runs],
                "training_run_ids": [run.run_id for run in train_runs],
                "test_run_ids": [run.run_id for run in test_runs],
                "stealth_generalization_training_run_ids": [run.run_id for run in general_train_runs],
                "stealth_generalization_test_run_ids": [run.run_id for run in general_test_runs],
                "models": model.metadata,
                "evaluation_files": ["held_out_evaluation.json", "stealth_generalization_evaluation.json"],
                "held_out_summary": {"nature_macro_f1": regular_report["nature"]["macro_f1"],
                    "origin_macro_f1": regular_report["origin"]["macro_f1"],
                    "detector_coverage": regular_report["detector_coverage"]},
                "stealth_generalization_summary": {
                    "nature_macro_f1": general_report["nature"]["macro_f1"],
                    "origin_macro_f1": general_report["origin"]["macro_f1"]}}
    (output / "telemetry_audit.json").write_text(
        json.dumps(summarize_telemetry(runs), indent=2), encoding="utf-8")
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(output), "runs": len(runs), "class_run_counts": class_counts,
        "held_out_nature_macro_f1": regular_report["nature"]["macro_f1"],
        "held_out_origin_macro_f1": regular_report["origin"]["macro_f1"],
        "stealth_generalization_nature_macro_f1": general_report["nature"]["macro_f1"],
        "stealth_generalization_origin_macro_f1": general_report["origin"]["macro_f1"]}, indent=2))


if __name__ == "__main__":
    main()

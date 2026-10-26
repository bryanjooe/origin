"""Build/evaluate Stage B artifacts. Run with PYTHONPATH=backend python -m app.security_analysis."""

import argparse
import json
from pathlib import Path

from app.detection import AnomalyDetector
from .audit import summarize_telemetry
from .dataset import feature_frame, generate_runs, incident_sample, split_runs
from .evaluation import evaluate
from .features import FEATURE_NAMES
from .model import AttributionModels


def main():
    parser = argparse.ArgumentParser(description="Train/evaluate synthetic Origin Stage B classifiers")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--ticks", type=int, default=240)
    parser.add_argument("--seed", type=int, default=72100)
    parser.add_argument("--output-dir", default="outputs/stage4")
    parser.add_argument("--anomaly-model", default="outputs/stage2/anomaly.joblib")
    parser.add_argument("--source-model", default="outputs/stage3/source_classifier.joblib")
    args = parser.parse_args()
    output = Path(args.output_dir)
    detector_path = Path(args.anomaly_model)
    detector = AnomalyDetector.load(detector_path)
    runs = generate_runs(repeats=args.repeats, ticks=args.ticks, seed=args.seed)
    train_runs, test_runs = split_runs(runs, seed=args.seed)
    general_train_runs, general_test_runs = split_runs(runs, seed=args.seed + 1,
                                                        held_out_stealth="stealthy")

    samples = [item for run in train_runs if (item := incident_sample(run, detector)) is not None]
    if not samples:
        raise RuntimeError("No training run fired the existing anomaly detector")
    model = AttributionModels().fit(samples, seed=args.seed)
    model.save(output / "fault_attack_origin.joblib")

    def evaluate_split(name, split_train, split_test):
        fitted_samples = [item for run in split_train if (item := incident_sample(run, detector)) is not None]
        split_model = AttributionModels().fit(fitted_samples, seed=args.seed)
        report = evaluate(split_model, split_test, detector,
                          source_model_path=args.source_model if Path(args.source_model).exists() else None)
        report["training_run_count"] = len(split_train)
        report["training_detected_window_count"] = len(fitted_samples)
        report["held_out_stealth_level"] = "stealthy" if name == "stealth_generalization" else None
        (output / f"{name}_evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    regular_report = evaluate_split("held_out", train_runs, test_runs)
    general_report = evaluate_split("stealth_generalization", general_train_runs, general_test_runs)
    # Persist the complete raw feature corpus after inference. The CSV contains
    # one row per detected run and separates labels/metadata from allowlisted features.
    all_samples = [item for run in runs if (item := incident_sample(run, detector)) is not None]
    feature_frame(all_samples).to_csv(output / "incident_features.csv", index=False)
    metadata = {"provenance": "synthetic simulations only",
                "generator_seed": args.seed,
                "configuration": {"repeats_per_cell": args.repeats, "ticks_per_run": args.ticks,
                                 "severity_levels": [0.25, 0.6, 1.0],
                                 "stealth_levels": ["naive", "moderate", "stealthy"],
                                 "fault_modes": "all modes in backend/app/fault_injection/engine.py",
                                 "attack_types": "all AttackType values, including multi_stage",
                                 "anomaly_model": str(detector_path),
                                 "window_rule": "existing detector fire followed by causal 20-tick window",
                                 "split_unit": "complete run; unique run IDs and seeds"},
                "feature_version": 1, "feature_names": list(FEATURE_NAMES),
                "run_count": len(runs),
                "detected_window_count": len(all_samples),
                "detector_miss_count": len(runs) - len(all_samples),
                "run_manifests": [run.manifest() for run in runs],
                "training_run_ids": [run.run_id for run in train_runs],
                "test_run_ids": [run.run_id for run in test_runs],
                "stealth_generalization_training_run_ids": [run.run_id for run in general_train_runs],
                "stealth_generalization_test_run_ids": [run.run_id for run in general_test_runs],
                "models": model.metadata,
                "evaluation_files": ["held_out_evaluation.json", "stealth_generalization_evaluation.json"],
                "held_out_summary": {"nature_macro_f1": regular_report["nature"]["macro_f1"],
                                     "origin_macro_f1": regular_report["origin"]["macro_f1"]},
                "stealth_generalization_summary": {
                    "nature_macro_f1": general_report["nature"]["macro_f1"],
                    "origin_macro_f1": general_report["origin"]["macro_f1"]}}
    output.mkdir(parents=True, exist_ok=True)
    (output / "telemetry_audit.json").write_text(
        json.dumps(summarize_telemetry(runs), indent=2), encoding="utf-8")
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(output), "runs": len(runs),
                      "training_windows": len(samples),
                      "held_out_nature_macro_f1": regular_report["nature"]["macro_f1"],
                      "held_out_origin_macro_f1": regular_report["origin"]["macro_f1"],
                      "stealth_generalization_nature_macro_f1": general_report["nature"]["macro_f1"],
                      "stealth_generalization_origin_macro_f1": general_report["origin"]["macro_f1"]}, indent=2))


if __name__ == "__main__":
    main()

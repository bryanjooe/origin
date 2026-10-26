"""Train, calibrate, evaluate and save the Stage 2 normal-baseline detector."""
import argparse
import json
from pathlib import Path

from .dataset import fault_runs, feature_table, normal_runs
from .evaluation import evaluate
from .model import AnomalyDetector


def main():
    parser = argparse.ArgumentParser(description="Train and evaluate Stage 2 anomaly detection")
    parser.add_argument("--output", type=Path, default=Path("outputs/stage2"))
    parser.add_argument("--train-runs", type=int, default=24)
    parser.add_argument("--calibration-runs", type=int, default=8)
    parser.add_argument("--test-runs", type=int, default=8)
    parser.add_argument("--ticks", type=int, default=1440, help="Ticks per complete normal run")
    parser.add_argument("--warning-quantile", type=float, default=0.99)
    parser.add_argument("--critical-quantile", type=float, default=0.999)
    args = parser.parse_args()
    if args.ticks < 256:
        parser.error("--ticks must be >= 256")
    try:
        print("Generating independent normal training and calibration runs...", flush=True)
        train = normal_runs("train", args.train_runs, args.ticks)
        calibration = normal_runs("calibration", args.calibration_runs, args.ticks)
        model = AnomalyDetector().fit(train, calibration, warning_quantile=args.warning_quantile,
                                     critical_quantile=args.critical_quantile)
        print("Evaluating frozen model on held-out normal and fault runs...", flush=True)
        report = evaluate(model, normal_runs("test", args.test_runs, args.ticks), fault_runs())
    except ValueError as error:
        parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=True)
    model.save(args.output / "anomaly.joblib")
    feature_table(train).to_csv(args.output / "normal_training_features.csv", index=False)
    (args.output / "training_manifest.json").write_text(json.dumps(model.metadata, indent=2), encoding="utf-8")
    report["thresholds"] = {"warning": model.thresholds.warning, "critical": model.thresholds.critical}
    (args.output / "evaluation.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"training_rows": model.metadata["training_rows"],
                      "calibration_rows": model.metadata["calibration_rows"],
                      "thresholds": report["thresholds"], "performance": report["performance"],
                      "output": str(args.output.resolve())}, indent=2), flush=True)


if __name__ == "__main__":
    main()

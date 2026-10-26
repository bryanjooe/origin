"""Train on complete runs, assess validation, freeze, then evaluate final test runs."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from app.detection.dataset import validate_partitions
from .dataset import partition_runs, supervised_table
from .evaluation import evaluate
from .model import ConfidencePolicy, SourceLocalizer


def main():
    parser = argparse.ArgumentParser(description="Train and evaluate Stage 3 fault-source localization")
    parser.add_argument("--output", type=Path, default=Path("outputs/stage3"))
    parser.add_argument("--minimum-confidence", type=float, default=0.65)
    parser.add_argument("--minimum-margin", type=float, default=0.15)
    args = parser.parse_args()
    try:
        policy = ConfidencePolicy(args.minimum_confidence, args.minimum_margin)
        print("Generating independent complete training scenarios...", flush=True)
        train = partition_runs("train")
        model = SourceLocalizer(policy).fit(train)
        print("Evaluating validation scenarios with the preconfigured confidence policy...", flush=True)
        validation = partition_runs("validation")
        validate_partitions(train, validation)
        validation_report = evaluate(model, validation)
        print("Evaluating frozen model on independent test scenarios...", flush=True)
        test = partition_runs("test")
        validate_partitions(train, validation, test)
        report = evaluate(model, test)
    except ValueError as error:
        parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=True)
    model.save(args.output / "source_classifier.joblib")
    supervised_table(train).to_csv(args.output / "source_training_features.csv", index=False)
    (args.output / "training_manifest.json").write_text(json.dumps(model.metadata, indent=2), encoding="utf-8")
    report["policy"] = asdict(policy)
    report["validation_summary"] = {key: validation_report[key] for key in (
        "run_count", "rows", "raw_accuracy", "accuracy_including_unknown", "coverage", "accepted_accuracy")}
    for name, data in (("validation.json", validation_report), ("evaluation.json", report)):
        (args.output / name).write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"training_runs": len(train), "training_rows": model.metadata["training_rows"],
                      "policy": report["policy"],
                      **{key: report[key] for key in ("run_count", "rows", "raw_accuracy", "accuracy_including_unknown",
                                                     "accepted_accuracy", "coverage", "unknown_rate", "macro_f1")},
                      "output": str(args.output.resolve())}, indent=2), flush=True)


if __name__ == "__main__":
    main()

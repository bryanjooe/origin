"""Validation-only Stage B selection followed by one fresh held-out evaluation.

Run after diagnose_stage_b.py. Original artifacts are read-only. No frontend,
simulator, Phase 1 detector/localizer, or confidence threshold is changed.
"""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.inspection import permutation_importance

from app.detection import AnomalyDetector, FeatureExtractor
from app.security_analysis.dataset import AlertPolicy, generate_runs, live_incident_sample, simulate_scenario, split_runs
from app.security_analysis.evaluation import evaluate
from app.security_analysis.model import AttributionModels, NATURE_DISPLAY, ORIGIN_DISPLAY


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def task_metrics(rows, task):
    if task == "nature":
        expected = lambda row: NATURE_DISPLAY[row["nature_truth"]]
        key, abstention = "nature_prediction", "Undetermined"
    else:
        rows = [row for row in rows if row["origin_truth"] is not None]
        expected = lambda row: ORIGIN_DISPLAY[row["origin_truth"]]
        key, abstention = "origin_prediction", "Unknown"
    detected = [row for row in rows if row["inference_tick"] is not None]
    accepted = [row for row in detected if row[key] != abstention]
    return {"run_count": len(rows), "detected_window_count": len(detected), "accepted_count": len(accepted),
        "prediction_coverage_on_detected": len(accepted) / len(detected) if detected else 0,
        "prediction_coverage_all_runs": len(accepted) / len(rows) if rows else 0,
        "abstention_on_detected": sum(row[key] == abstention for row in detected) / len(detected) if detected else 0,
        "accepted_accuracy": sum(row[key] == expected(row) for row in accepted) / len(accepted) if accepted else 0,
        "accuracy_on_detected_including_abstention": sum(row[key] == expected(row) for row in detected) / len(detected) if detected else 0,
        "overall_accuracy_including_abstention_and_misses": sum(row[key] == expected(row) for row in rows) / len(rows) if rows else 0}


def summary(report):
    rows = report["row_level_results"]
    result = {"nature_macro_f1": report["nature"]["macro_f1"], "origin_macro_f1": report["origin"]["macro_f1"],
        "nature": task_metrics(rows, "nature"), "origin": task_metrics(rows, "origin"),
        "normal_false_attack_rate": report["normal_run_false_positive_rate"]["nature_classifier_attack_label"],
        "detector_coverage": report["detector_coverage"], "delay": report["attack_detection_delay_ticks"],
        "counts_by_nature": dict(Counter(row["nature_truth"] for row in rows)),
        "detection_by_nature": {nature: {"count": sum(row["nature_truth"] == nature for row in rows),
            "detected": sum(row["nature_truth"] == nature and row["inference_tick"] is not None for row in rows)}
            for nature in ("normal", "fault", "attack")}}
    return result


def acceptable(baseline, candidate):
    """Predeclared non-regression checks, applied identically before/after holdout."""
    return (candidate["nature_macro_f1"] >= baseline["nature_macro_f1"] - 0.01
        and candidate["origin_macro_f1"] >= baseline["origin_macro_f1"] - 0.01
        and candidate["nature"]["accepted_accuracy"] >= baseline["nature"]["accepted_accuracy"] - 0.02
        and candidate["origin"]["accepted_accuracy"] >= baseline["origin"]["accepted_accuracy"] - 0.02
        and candidate["normal_false_attack_rate"] <= baseline["normal_false_attack_rate"] + 0.01)


def report_for(model, runs, detector, policy, samples):
    report = evaluate(model, runs, detector, alert_policy=policy,
        sample_builder=lambda run, *_: samples.get(run.run_id), compute_importance=False)
    report["window_rule"] = "first Stage B gate within the existing incident lifecycle; 20 complete observed ticks; no hidden event-end clipping"
    report["protocol"] = "live_incident_v1"
    report["reliability"] = summary(report)
    return report


def finalize(args, regular, stealth):
    promotable = regular["selection"] != "original" and regular["passes_frozen_test_guards"] and stealth["passes_frozen_test_guards"]
    write(args.output / "promotion_decision.json", {"regular": regular, "stealth": stealth,
        "promotable": promotable, "no_test_driven_reselection": True})
    path = args.output / "regular/selected.joblib"
    original = AttributionModels.load("outputs/step5/original/held_out_fault_attack_origin.joblib")
    selected = AttributionModels.load(path)
    write(args.output.parent / "promoted.json", {"revision": "step5-independent-origin-v1", "promotable": promotable,
        "artifact": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "nature_weights_unchanged": joblib.hash(original.nature_model) == joblib.hash(selected.nature_model),
        "origin_weights_unchanged": joblib.hash(original.origin_model) == joblib.hash(selected.origin_model),
        "thresholds": asdict(selected.policy), "feature_version": selected.metadata["feature_version"],
        "original_artifact_preserved": True, "activation": "scripts/run_reliable_api.ps1"})


def train_split(name, train, validation, test, samples, detector, baseline, policy, args, extra):
    output = args.output / name
    output.mkdir(parents=True, exist_ok=True)
    train, calibration_runs = split_runs(train, test_fraction=0.2, seed=args.seed + 13)
    fit_samples = [samples[run.run_id] for run in train if run.run_id in samples] + extra["fit"]
    calibration = [samples[run.run_id] for run in calibration_runs if run.run_id in samples] + extra["calibration"]
    populations = {"fit": train, "calibration": calibration_runs, "validation": validation, "test": test}
    for a, left in populations.items():
        for b, right in populations.items():
            if a != b:
                assert {run.run_id for run in left}.isdisjoint(run.run_id for run in right)
                assert {run.seed for run in left}.isdisjoint(run.seed for run in right)
    baseline_validation = report_for(baseline, validation, detector, policy, samples)
    write(output / "baseline_validation.json", baseline_validation)
    candidates = {"original": baseline}
    independent = deepcopy(baseline)
    independent.metadata = {**independent.metadata, "origin_requires_determined_nature": False,
        "window_protocol": "legacy fitting; separately evaluated with live_incident_v1 windows"}
    candidates["independent_origin"] = independent
    print(name, "fit windows", len(fit_samples), dict(Counter(item["nature"] for item in fit_samples)), flush=True)
    for calibrated in (False, True):
        label = "random_forest_calibrated" if calibrated else "random_forest"
        try:
            model = AttributionModels(baseline.policy).fit(fit_samples, seed=args.seed,
                algorithm="random_forest", calibration_samples=calibration if calibrated else None)
            model.metadata.update(origin_requires_determined_nature=False, window_protocol="live_incident_v1",
                training_configuration={"seed": args.seed, "repeats": args.repeats, "ticks": args.ticks,
                    "algorithm_parameters": {"n_estimators": 320, "max_depth": 16, "min_samples_leaf": 2, "class_weight": "balanced", "n_jobs": 1},
                    "thresholds": asdict(model.policy), "complete_run_splits": True})
            candidates[label] = model
        except ValueError as error:
            write(output / f"{label}_not_fitted.json", {"reason": str(error)})
    scores = {}
    for label, model in candidates.items():
        report = report_for(model, validation, detector, policy, samples)
        scores[label] = report["reliability"]
        write(output / f"{label}_validation.json", report)
        print(name, label, "validation F1", scores[label]["nature_macro_f1"], scores[label]["origin_macro_f1"], flush=True)
        if label != "original":
            model.save(output / f"{label}.joblib")
    eligible = [label for label in candidates if acceptable(scores["original"], scores[label])]
    selected = max(eligible, key=lambda label: (scores[label]["nature_macro_f1"] + scores[label]["origin_macro_f1"],
        scores[label]["nature"]["accepted_accuracy"], label == "original"))
    model = candidates[selected]
    selection = {"selected": selected, "selected_using": "validation only; all thresholds unchanged",
        "guards": {"macro_f1_max_regression": 0.01, "accepted_accuracy_max_regression": 0.02, "normal_fpr_max_increase": 0.01},
        "validation": scores, "thresholds": asdict(model.policy),
        "splits": {key: [{"run_id": run.run_id, "seed": run.seed} for run in values] for key, values in populations.items()},
        "window_counts": {key: dict(Counter(samples[run.run_id]["nature"] for run in values if run.run_id in samples)) for key, values in populations.items()},
        "additional_normal_windows": {key: len(value) for key, value in extra.items()},
        "extra_normal_training_seeds": {key: [item["seed"] for item in value] for key, value in extra.items()}}
    # This decision is written before either model sees the final test outcomes.
    write(output / "selection_before_test.json", selection)
    model.save(output / "selected.joblib")
    before = report_for(baseline, test, detector, policy, samples)
    after = report_for(model, test, detector, policy, samples)
    write(output / "baseline_held_out.json", before)
    write(output / "held_out_evaluation.json", after)
    comparison = {"selection": selected, "sample_count": len(test), "before": before["reliability"],
        "after": after["reliability"], "passes_frozen_test_guards": acceptable(before["reliability"], after["reliability"])}
    write(output / "comparison.json", comparison)
    x = np.asarray([[item["features"][feature] for feature in model.metadata["feature_names"]] for item in calibration])
    y = np.asarray([item["nature"] for item in calibration])
    if len(calibration):
        importance = permutation_importance(model.nature_model, x, y, scoring="f1_macro", n_repeats=3, random_state=args.seed, n_jobs=1)
        write(output / "validation_feature_importance.json", sorted([
            {"feature": feature, "importance": float(value)} for feature, value in zip(model.metadata["feature_names"], importance.importances_mean)], key=lambda item: -item["importance"]))
    print(name, "FINAL", json.dumps(comparison), flush=True)
    return comparison


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=841600)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--ticks", type=int, default=240)
    parser.add_argument("--extra-normal-runs", type=int, default=1200)
    parser.add_argument("--stealth-only", action="store_true")
    parser.add_argument("--finalize-only", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("outputs/step5/candidates"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.finalize_only:
        finalize(args, json.loads((args.output / "regular/comparison.json").read_text()),
                 json.loads((args.output / "stealth_generalization/comparison.json").read_text()))
        return
    baseline = AttributionModels.load("outputs/step5/original/held_out_fault_attack_origin.joblib")
    detector = AnomalyDetector.load("outputs/stage2/anomaly.joblib")
    old_report = json.loads(Path("outputs/step5/original/held_out_evaluation.json").read_text())
    policy = AlertPolicy(**old_report["alert_policy"])
    cache = args.output / "observed_samples.joblib"
    if cache.exists():
        saved = joblib.load(cache)
        assert all(saved["configuration"][key] == getattr(args, key) for key in ("seed", "repeats", "ticks"))
        runs, samples = saved["runs"], saved["samples"]
    else:
        runs = generate_runs(repeats=args.repeats, ticks=args.ticks, seed=args.seed)
        samples = {}
        for index, run in enumerate(runs):
            run.run_id = f"reliability-{args.seed}-{run.run_id}"
            assert run.seed not in baseline.metadata["training_seeds"]
            sample = live_incident_sample(run, detector, policy)
            if sample is not None:
                samples[run.run_id] = sample
            if index % 100 == 0:
                print("Observed window preparation", index, "/", len(runs), flush=True)
        # Telemetry is discarded only from the cached manifests after real feature
        # extraction; held-out labels remain separate from inference features.
        for run in runs:
            run.telemetry = []
        joblib.dump({"configuration": vars(args), "runs": runs, "samples": samples}, cache)
    write(args.output / "corpus.json", {"seed": args.seed, "ticks": args.ticks, "repeats": args.repeats,
        "class_counts": dict(Counter(run.nature for run in runs)), "window_counts": dict(Counter(item["nature"] for item in samples.values())),
        "run_manifests": [{**run.manifest(), "ticks": args.ticks} for run in runs], "training_seed_overlap_with_original": False,
        "normal_sampling": "same existing generator; 60 normal runs per repeat; full evaluation distributions retained"})
    extra_cache = args.output / "normal_training_augmentation.joblib"
    if extra_cache.exists():
        saved_extra = joblib.load(extra_cache)
        assert saved_extra["run_count"] == args.extra_normal_runs
        extra = saved_extra["samples"]
    else:
        extra = {"fit": [], "calibration": []}
        manifests = []
        for index in range(args.extra_normal_runs):
            seed = 2000000 + index * 17
            assert seed not in {run.seed for run in runs} and seed not in baseline.metadata["training_seeds"]
            run = simulate_scenario(f"normal-augmentation-{seed}", seed, ticks=args.ticks)
            manifests.append(run.manifest())
            sample = live_incident_sample(run, detector, policy)
            if sample is not None:
                extra["calibration" if index % 5 == 0 else "fit"].append(sample)
            if index % 100 == 0:
                print("Normal training augmentation", index, "/", args.extra_normal_runs, flush=True)
        joblib.dump({"run_count": args.extra_normal_runs, "samples": extra, "manifests": manifests}, extra_cache)
    regular_train, regular_test = split_runs(runs, seed=args.seed)
    fit, validation = split_runs(regular_train, test_fraction=0.2, seed=args.seed + 11)
    regular = json.loads((args.output / "regular/comparison.json").read_text()) if args.stealth_only else train_split("regular", fit, validation, regular_test, samples, detector, baseline, policy, args, extra)
    # The generalization reference must itself have excluded stealthy runs.
    stealth_baseline = AttributionModels.load("outputs/step5/original/stealth_generalization_fault_attack_origin.joblib")
    stealth_report = json.loads(Path("outputs/step5/original/stealth_generalization_evaluation.json").read_text())
    stealth_policy = AlertPolicy(**stealth_report["alert_policy"])
    original_metadata = json.loads(Path("outputs/step5/original/metadata.json").read_text())
    original_manifests = {run["run_id"]: run for run in original_metadata["run_manifests"]}
    assert all(original_manifests[run_id]["stealth_level"] != "stealthy" for run_id in stealth_baseline.metadata["training_run_ids"])
    stealth_cache = args.output / "stealth_observed_samples.joblib"
    if stealth_cache.exists():
        stored = joblib.load(stealth_cache)
        assert stored["policy"] == asdict(stealth_policy)
        stealth_samples, stealth_extra = stored["samples"], stored["extra"]
    else:
        stealth_samples = {}
        for index, manifest in enumerate(runs):
            run = simulate_scenario(manifest.run_id, manifest.seed, nature=manifest.nature,
                scenario_type=manifest.scenario_type, mode=manifest.mode, origin_layer=manifest.origin_layer,
                stealth_level=manifest.stealth_level, severity=manifest.severity,
                start_tick=manifest.start_tick, duration_ticks=manifest.duration_ticks, ticks=args.ticks,
                config=manifest.config, target_component=manifest.target_component)
            sample = live_incident_sample(run, detector, stealth_policy)
            if sample is not None:
                stealth_samples[run.run_id] = sample
            if index % 200 == 0:
                print("Dedicated stealth-policy windows", index, "/", len(runs), flush=True)
        stealth_extra = {"fit": [], "calibration": []}
        for index in range(args.extra_normal_runs):
            seed = 2000000 + index * 17
            run = simulate_scenario(f"normal-augmentation-{seed}", seed, ticks=args.ticks)
            sample = live_incident_sample(run, detector, stealth_policy)
            if sample is not None:
                stealth_extra["calibration" if index % 5 == 0 else "fit"].append(sample)
            if index % 200 == 0:
                print("Dedicated stealth-policy normal windows", index, "/", args.extra_normal_runs, flush=True)
        joblib.dump({"policy": asdict(stealth_policy), "samples": stealth_samples, "extra": stealth_extra}, stealth_cache)
    stealth_train, stealth_test = split_runs(runs, seed=args.seed + 1, held_out_stealth="stealthy")
    fit, validation = split_runs(stealth_train, test_fraction=0.2, seed=args.seed + 12)
    assert not any(run.stealth_level == "stealthy" for run in fit + validation)
    stealth = train_split("stealth_generalization", fit, validation, stealth_test, stealth_samples, detector, stealth_baseline, stealth_policy, args, stealth_extra)
    # Runtime-compatible genuine report bundle; originals remain untouched.
    regular_root = args.output / "regular"
    write(regular_root / "stealth_generalization_evaluation.json", json.loads((args.output / "stealth_generalization/held_out_evaluation.json").read_text()))
    selected = AttributionModels.load(regular_root / "selected.joblib")
    write(regular_root / "metadata.json", {"provenance": "fresh seeded synthetic simulation runs; validation-only selection; live-aligned windows",
        "generator_seed": args.seed, "run_count": len(runs), "class_run_counts": dict(Counter(run.nature for run in runs)),
        "feature_names": selected.metadata["feature_names"], "feature_version": selected.metadata["feature_version"],
        "models": selected.metadata, "selection": regular["selection"], "original_artifact_sha256": hashlib.sha256(Path("outputs/step5/original/held_out_fault_attack_origin.joblib").read_bytes()).hexdigest()})
    finalize(args, regular, stealth)


if __name__ == "__main__":
    main()

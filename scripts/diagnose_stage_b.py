"""Reproduce live Stage B decisions and the original evaluation without training."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import joblib

from app.api.config import ServerSettings
from app.api.runtime import SimulationRuntime
from app.detection import AnomalyDetector, FeatureExtractor
from app.explainability.incidents import IncidentTracker
from app.schemas.api import AttackRequest, FaultRequest
from app.security_analysis.dataset import AlertPolicy, generate_runs, incident_sample, simulate_scenario
from app.security_analysis.evaluation import evaluate
from app.security_analysis.features import extract_window
from app.security_analysis.model import AttributionModels
from app.simulator import GridConfig, MicrogridSimulator


async def diagnose(output, seeds, model_path=None, results_path=None, filename="live_diagnosis_before.json"):
    cases = [
        ("inverter_shutdown", "fault", {"kind": "inverter", "mode": "shutdown", "severity": 1}),
        ("sensor_bias", "fault", {"kind": "sensor", "mode": "bias", "severity": 0.8}),
        ("message_tampering", "attack", {"attack_type": "message_tampering", "target_component": "communication", "severity": 0.8, "stealth_level": "naive"}),
        ("replay", "attack", {"attack_type": "replay", "target_component": "communication", "severity": 0.8, "stealth_level": "naive"}),
        ("communication_degradation", "attack", {"attack_type": "communication_degradation", "target_component": "communication", "severity": 0.8, "stealth_level": "naive"}),
        ("sensor_spoof", "attack", {"attack_type": "sensor_spoof", "target_component": "solar_sensor", "severity": 0.8, "stealth_level": "naive"}),
        ("stealth_sensor_spoof", "attack", {"attack_type": "sensor_spoof", "target_component": "solar_sensor", "severity": 0.25, "stealth_level": "stealthy"}),
        ("actuator_abuse", "attack", {"attack_type": "actuator_abuse", "target_component": "inverter", "severity": 1, "stealth_level": "naive"}),
        ("normal", "normal", {}),
    ]
    results = []
    settings = ServerSettings(database_path=":memory:")
    if model_path is not None:
        settings.security_model = model_path
    if results_path is not None:
        settings.security_results_dir = results_path
    runtime = SimulationRuntime(settings)
    try:
        for seed in seeds:
            for name, truth, body in cases:
                await runtime.reset(seed=seed)
                if truth == "fault":
                    await runtime.inject(FaultRequest(**body, start_tick=0, duration_ticks=120))
                elif truth == "attack":
                    await runtime.inject_attack(AttackRequest(**body, start_tick=0, duration_ticks=120))
                await runtime.step(160)
                items = runtime.store.incidents(run_id=runtime.run_id)["items"]
                incidents = []
                for item in items:
                    report = runtime.store.incident(item["id"])
                    a = report["security_attribution"]
                    record = {"first_anomaly_tick": report["first_observed_tick"], "confirmed_tick": report["detection_tick"], "assessment": a}
                    if a["available"]:
                        start = a["window_start_tick"]
                        rows = [r["telemetry"] for r in runtime.store.telemetry(runtime.run_id, -1, 10000)]
                        config = runtime.sim.config
                        features = extract_window(rows[start:start + 20], baseline_rows=rows[max(0, start - 20):start],
                            solar_capacity_kw=config.solar_capacity_kw, battery_capacity_kwh=config.battery_capacity_kwh,
                            tick_seconds=config.tick_seconds, communication_delay_ticks=config.communication_delay_ticks,
                            charge_efficiency=config.charge_efficiency, discharge_efficiency=config.discharge_efficiency)
                        p = runtime.models.security_analyzer.predict_features(features)
                        nature = sorted(p["nature_candidates"], key=lambda x: -x["confidence"])
                        origin = p["origin_candidates"]
                        policy = runtime.models.security_analyzer.policy
                        record.update(features=features, nature_margin=nature[0]["confidence"]-nature[1]["confidence"],
                            origin_margin=origin[0]["confidence"]-origin[1]["confidence"], thresholds=asdict(policy),
                            nature_below_minimum=nature[0]["confidence"] < policy.nature_minimum,
                            nature_margin_too_small=nature[0]["confidence"]-nature[1]["confidence"] < policy.margin_minimum,
                            origin_below_minimum=origin[0]["confidence"] < policy.origin_minimum,
                            origin_margin_too_small=origin[0]["confidence"]-origin[1]["confidence"] < policy.margin_minimum,
                            origin_suppressed_by_nature=p["nature"] == "Undetermined" and p["origin"] == "Unknown",
                            classification_delay_ticks=a["inference_tick"])
                    incidents.append(record)
                results.append({"scenario": name, "seed": seed, "evaluation_only_truth": truth, "phase1_detected": bool(items), "incidents": incidents})
                print(seed, name, [(i["assessment"]["status"], i["assessment"]["nature_verdict"], i["assessment"]["origin"]) for i in incidents], flush=True)
        equivalence = []
        for seed in seeds:
            fault, attack = MicrogridSimulator(GridConfig(), seed), MicrogridSimulator(GridConfig(), seed)
            fault.inject("inverter", "shutdown", severity=1, start_tick=0, duration_ticks=120)
            attack.inject_attack("actuator_abuse", "inverter", severity=1, start_tick=0, duration_ticks=120, stealth_level="naive")
            equivalence.append({"seed": seed, "observable_rows_identical": fault.run(160) == attack.run(160)})
        payload = {"provenance": "actual live runtime with unchanged saved artifacts; labels are offline evaluation only",
                   "cases": results, "inverter_fault_attack_equivalence": equivalence}
        (output / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    finally:
        await runtime.close()


def original_baseline(output):
    root = Path("outputs/step5/original")
    metadata = json.loads((root / "metadata.json").read_text())
    config = metadata["configuration"]
    runs = generate_runs(repeats=config["repeats_per_cell"], ticks=config["ticks_per_run"], seed=metadata["generator_seed"])
    detector = AnomalyDetector.load("outputs/stage2/anomaly.joblib")
    for split, ids in (("held_out", metadata["test_run_ids"]), ("stealth_generalization", metadata["stealth_generalization_test_run_ids"])):
        model = AttributionModels.load(root / f"{split}_fault_attack_origin.joblib")
        saved = json.loads((root / f"{split}_evaluation.json").read_text())
        selected = [run for run in runs if run.run_id in set(ids)]
        report = evaluate(model, selected, detector, alert_policy=AlertPolicy(**saved["alert_policy"]))
        (output / f"original_{split}_baseline.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(split, "recomputed", len(selected), "runs; nature F1", report["nature"]["macro_f1"], "origin F1", report["origin"]["macro_f1"], flush=True)


def audit_windows(output):
    saved = joblib.load(output / "candidates/observed_samples.joblib")
    selection = json.loads((output / "candidates/regular/selection_before_test.json").read_text())
    ids = {item["run_id"] for item in selection["splits"]["test"]}
    policy = AlertPolicy(**json.loads((output / "original/held_out_evaluation.json").read_text())["alert_policy"])
    detector = AnomalyDetector.load("outputs/stage2/anomaly.joblib")
    records = []
    for manifest in saved["runs"]:
        if manifest.run_id not in ids:
            continue
        run = simulate_scenario(manifest.run_id, manifest.seed, nature=manifest.nature,
            scenario_type=manifest.scenario_type, mode=manifest.mode, origin_layer=manifest.origin_layer,
            stealth_level=manifest.stealth_level, severity=manifest.severity, start_tick=manifest.start_tick,
            duration_ticks=manifest.duration_ticks, ticks=240, config=manifest.config,
            target_component=manifest.target_component)
        legacy = incident_sample(run, detector, policy)
        live = saved["samples"].get(run.run_id)
        statuses = detector.predict(FeatureExtractor(run.config).transform(run.telemetry))
        tracker = IncidentTracker()
        for row, status in zip(run.telemetry, statuses):
            tracker.update(row, status)
        alerts = [status for status in statuses if status["combined_status"] != "normal"]
        event_alert = any(run.start_tick <= status["tick"] < run.start_tick + run.duration_ticks for status in alerts) if run.nature != "normal" else bool(alerts)
        same_window = bool(legacy and live and legacy["detector_fire_tick"] == live["detector_fire_tick"] and legacy["inference_tick"] == live["inference_tick"])
        records.append({"run_id": run.run_id, "nature_truth": run.nature,
            "phase1_any_alert": bool(alerts), "phase1_alert_during_event": event_alert,
            "phase1_confirmed_incident_count": len(tracker.reports()),
            "legacy_detected": legacy is not None, "live_detected": live is not None,
            "legacy_window_ticks": len(legacy["telemetry_window"]) if legacy else None,
            "same_window": same_window, "identical_features_for_same_window": legacy["features"] == live["features"] if same_window else None})
    result = {"runs": len(records), "legacy_detected": sum(row["legacy_detected"] for row in records),
        "live_detected": sum(row["live_detected"] for row in records),
        "legacy_short_windows": sum(row["legacy_window_ticks"] is not None and row["legacy_window_ticks"] < 20 for row in records),
        "same_window_count": sum(row["same_window"] for row in records),
        "same_window_feature_mismatches": sum(row["identical_features_for_same_window"] is False for row in records),
        "separate_detection_stages": {nature: {"runs": sum(row["nature_truth"] == nature for row in records),
            "phase1_alerted": sum(row["nature_truth"] == nature and row["phase1_any_alert"] for row in records),
            "phase1_alert_during_event": sum(row["nature_truth"] == nature and row["phase1_alert_during_event"] for row in records),
            "confirmed_incident_runs": sum(row["nature_truth"] == nature and row["phase1_confirmed_incident_count"] > 0 for row in records),
            "stage_b_ready_windows": sum(row["nature_truth"] == nature and row["live_detected"] for row in records)}
            for nature in ("normal", "fault", "attack")},
        "records": records}
    (output / "window_protocol_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print({key: value for key, value in result.items() if key != "records"}, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("outputs/step5"))
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 73, 101])
    parser.add_argument("--original-baseline", action="store_true")
    parser.add_argument("--audit-windows", action="store_true")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--filename", default="live_diagnosis_before.json")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.audit_windows:
        audit_windows(args.output)
    elif args.original_baseline:
        original_baseline(args.output)
    else:
        asyncio.run(diagnose(args.output, args.seeds, args.model, args.results, args.filename))


if __name__ == "__main__":
    main()

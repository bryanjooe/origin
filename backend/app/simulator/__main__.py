"""Offline simulator demo with optional anomaly and source model scoring."""
import argparse
import csv
import json
from pathlib import Path

from app.fault_injection.engine import MODES, FaultKind
from app.propagation import build_topology
from .model import MicrogridSimulator


def main():
    parser = argparse.ArgumentParser(description="Origin — Stage 1 microgrid simulator")
    parser.add_argument("--ticks", type=int, default=180)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fault", choices=["normal"] + [kind.value for kind in FaultKind], default="normal")
    parser.add_argument("--mode", help="Fault mode; defaults to the first mode for the selected family")
    parser.add_argument("--severity", type=float, default=0.8)
    parser.add_argument("--start", type=int, default=30)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--correct-at", type=int)
    parser.add_argument("--output", type=Path, default=Path("outputs/demo"))
    parser.add_argument("--anomaly-model", type=Path, help="Optional trusted Stage 2 Joblib artifact")
    parser.add_argument("--source-model", type=Path, help="Optional trusted Stage 3 Joblib artifact")
    parser.add_argument("--investigate", action="store_true", help="Export evidence-grounded incident reports (requires --anomaly-model)")
    args = parser.parse_args()
    if args.investigate and not args.anomaly_model:
        parser.error("--investigate requires --anomaly-model; no anomaly predictions will be fabricated")
    if args.ticks < 1:
        parser.error("--ticks must be positive")
    if args.correct_at is not None and not 0 <= args.correct_at < args.ticks:
        parser.error("--correct-at must be within the run")
    sim = MicrogridSimulator(seed=args.seed)
    detector = extractor = None
    localizer = source_extractor = None
    if args.anomaly_model:
        from app.detection import AnomalyDetector, FeatureExtractor
        try:
            detector = AnomalyDetector.load(args.anomaly_model)
        except (FileNotFoundError, ValueError) as error:
            parser.error(f"Anomaly model unavailable: {error}")
        extractor = FeatureExtractor(sim.config)
    if args.source_model:
        from app.localization import LocalizationFeatureExtractor, SourceLocalizer
        try:
            localizer = SourceLocalizer.load(args.source_model)
        except (FileNotFoundError, ValueError) as error:
            parser.error(f"Source model unavailable: {error}")
        source_extractor = LocalizationFeatureExtractor(sim.config)
    if args.fault != "normal":
        kind = FaultKind(args.fault)
        mode = args.mode or {"sensor": "bias", "communication": "delay",
                             "controller": "wrong_dispatch", "firmware": "discharge_limit",
                             "inverter": "derate"}[args.fault]
        if mode not in MODES[kind]:
            parser.error(f"Valid modes for {args.fault}: {', '.join(sorted(MODES[kind]))}")
        try:
            sim.inject(kind, mode, args.severity, args.duration, args.start)
        except ValueError as error:
            parser.error(str(error))
    observations = []
    source_observations = []
    for tick in range(args.ticks):
        if tick == args.correct_at:
            sim.correct()
        row = sim.step()
        if extractor is not None:
            observations.append(extractor.update(row))
        if source_extractor is not None:
            source_observations.append(source_extractor.update(row))
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "telemetry.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(sim.history[0]))
        writer.writeheader()
        for row in sim.history:
            writer.writerow({**row, "controller_inputs": json.dumps(row["controller_inputs"])})
    (args.output / "telemetry.json").write_text(json.dumps(sim.history, indent=2), encoding="utf-8")
    (args.output / "scenario_ground_truth.json").write_text(json.dumps({
        **sim.settings(), "faults": sim.faults.ground_truth(), "events": sim.events,
    }, indent=2), encoding="utf-8")
    graph = build_topology()
    (args.output / "topology.json").write_text(json.dumps({
        "nodes": [{"id": node, **data} for node, data in graph.nodes(data=True)],
        "edges": [{"source": a, "target": b, **data} for a, b, data in graph.edges(data=True)],
    }, indent=2), encoding="utf-8")
    detection = source_predictions = None
    if detector is not None:
        detection = detector.predict(observations)
        (args.output / "anomaly_scores.json").write_text(json.dumps(detection, indent=2), encoding="utf-8")
        (args.output / "anomaly_events.json").write_text(json.dumps([
            row for row in detection if row["combined_status"] != "normal"
        ], indent=2), encoding="utf-8")
    if localizer is not None:
        source_predictions = localizer.predict(source_observations)
        (args.output / "source_predictions.json").write_text(
            json.dumps(source_predictions, indent=2), encoding="utf-8")
    if args.investigate:
        from app.explainability.incidents import investigate
        incidents = investigate(sim.history, detection, source_predictions)
        (args.output / "incidents.json").write_text(json.dumps(incidents, indent=2, allow_nan=False), encoding="utf-8")
    dt = sim.config.tick_seconds / 3600
    print(json.dumps({"ticks": args.ticks, "seed": args.seed,
                      "solar_generated_kwh": sum(r["actual_solar_kw"] for r in sim.history) * dt,
                      "demand_served_kwh": sum(r["delivered_kw"] for r in sim.history) * dt,
                      "unmet_demand_kwh": sum(r["unmet_demand_kw"] for r in sim.history) * dt,
                      "final_soc_pct": sim.history[-1]["battery_soc_pct"],
                      "output": str(args.output.resolve())}, indent=2))


if __name__ == "__main__":
    main()

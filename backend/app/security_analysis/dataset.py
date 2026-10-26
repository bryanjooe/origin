"""Deterministic whole-run corpus generation with observable-only feature columns."""

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random

import pandas as pd
import numpy as np

from app.attack_injection import AttackType, StealthLevel
from app.detection import AnomalyDetector, FeatureExtractor
from app.fault_injection import Fault
from app.fault_injection.engine import MODES
from app.simulator import GridConfig, MicrogridSimulator
from .features import FEATURE_NAMES, WINDOW_TICKS, extract_window


@dataclass(frozen=True)
class AlertPolicy:
    """Run-level alert gate calibrated on separate complete validation runs."""
    score_threshold: float
    warmup_ticks: int = 12
    persistence_ticks: int = 2
    repeated_rule_ticks: int = 3

    def __post_init__(self):
        if self.score_threshold < 0 or self.warmup_ticks < 0 or min(
                self.persistence_ticks, self.repeated_rule_ticks) < 1:
            raise ValueError("Invalid alert policy")


def _first_policy_fire(statuses, policy):
    score_run, rule_runs = 0, {}
    for result in statuses:
        tick = result["tick"]
        if tick < policy.warmup_ticks:
            continue
        score_run = score_run + 1 if result["anomaly_score"] >= policy.score_threshold else 0
        if score_run >= policy.persistence_ticks:
            return tick - policy.persistence_ticks + 1
        current = {check["signal"] for check in result["residual_checks"]}
        for signal in list(rule_runs):
            rule_runs[signal] = rule_runs[signal] + 1 if signal in current else 0
        for signal in current:
            rule_runs[signal] = rule_runs.get(signal, 0) + 1
        if len(current) >= 2 or any(count >= policy.repeated_rule_ticks for count in rule_runs.values()):
            return tick
    return None


def calibrate_alert_policy(validation_runs, detector, *, max_normal_false_alert_rate=0.05):
    """Choose a run-level threshold/gate using validation runs only."""
    normals = [run for run in validation_runs if run.nature == "normal"]
    if not normals or not any(run.nature != "normal" for run in validation_runs):
        raise ValueError("Alert calibration requires normal and event validation runs")
    normal_maxima, statuses_by_id = [], {}
    for run in validation_runs:
        statuses = detector.predict(FeatureExtractor(run.config).transform(run.telemetry))
        statuses_by_id[run.run_id] = statuses
        if run.nature == "normal":
            normal_maxima.append(max((r["anomaly_score"] for r in statuses
                                      if r["tick"] >= 12), default=0.0))
    candidates = []
    for quantile in (0.90, 0.95, 0.975, 0.99, 1.0):
        threshold = math.nextafter(float(np.quantile(normal_maxima, quantile)), math.inf)
        for persistence in (1, 2, 3, 4):
            policy = AlertPolicy(threshold, 12, persistence, 3)
            false_rate = sum(_first_policy_fire(statuses_by_id[run.run_id], policy) is not None
                             for run in normals) / len(normals)
            if false_rate > max_normal_false_alert_rate:
                continue
            event_runs = [run for run in validation_runs if run.nature != "normal"]
            covered = sum((fire := _first_policy_fire(statuses_by_id[run.run_id], policy)) is not None
                          and run.start_tick <= fire < run.start_tick + run.duration_ticks
                          for run in event_runs)
            candidates.append((covered / len(event_runs), -false_rate, -persistence,
                               policy, false_rate))
    if not candidates:
        threshold = float(np.max(normal_maxima))
        return AlertPolicy(threshold, 12, 3, 3), {"validation_normal_false_alert_rate": 0.0,
            "validation_event_coverage": 0.0, "constraint_met": False}
    best = max(candidates, key=lambda item: item[:3])
    return best[3], {"validation_normal_false_alert_rate": best[4],
                     "validation_event_coverage": best[0], "constraint_met": True,
                     "validation_normal_run_count": len(normals),
                     "validation_event_run_count": len(validation_runs) - len(normals),
                     "selection_rule": "maximum event coverage with normal run false-alert rate <= 5%"}


ATTACK_TARGETS = {
    AttackType.SENSOR_SPOOF: ("solar_sensor", "battery_sensor", "demand_sensor"),
    AttackType.REPLAY: ("communication",),
    AttackType.COMMUNICATION_DEGRADATION: ("communication",),
    AttackType.MESSAGE_TAMPERING: ("communication", "controller", "inverter"),
    AttackType.CONTROLLER_COMPROMISE: ("controller",),
    AttackType.FIRMWARE_TAMPERING: ("firmware",),
    AttackType.ACTUATOR_ABUSE: ("inverter",),
    AttackType.MULTI_STAGE: ("communication",),
}


@dataclass
class SimulatedRun:
    run_id: str
    seed: int
    telemetry: list[dict]
    nature: str
    origin_layer: str | None
    scenario_type: str
    mode: str | None
    stealth_level: str | None
    severity: float | None
    start_tick: int
    duration_ticks: int
    config: GridConfig
    target_component: str | None = None

    def manifest(self):
        return {"run_id": self.run_id, "seed": self.seed, "nature": self.nature,
                "origin_layer": self.origin_layer, "scenario_type": self.scenario_type,
                "mode": self.mode, "stealth_level": self.stealth_level,
                "severity": self.severity, "start_tick": self.start_tick,
                "duration_ticks": self.duration_ticks, "ticks": len(self.telemetry),
                "target_component": self.target_component, "config": asdict(self.config)}


def _config_for(seed):
    rng = random.Random(seed)
    return GridConfig(start_hour=rng.choice([6.5, 9, 10, 13, 16]),
                      solar_capacity_kw=rng.uniform(10, 14),
                      base_demand_kw=rng.uniform(6, 8),
                      battery_capacity_kwh=rng.uniform(20, 30),
                      initial_soc_pct=rng.uniform(35, 85),
                      communication_delay_ticks=rng.choice([0, 0, 1]),
                      packet_loss_probability=rng.choice([0, 0, 0.005]))


def simulate_scenario(run_id, seed, *, nature="normal", scenario_type="normal",
                      mode=None, origin_layer=None, stealth_level=None, severity=None,
                      start_tick=0, duration_ticks=0, ticks=240, config=None,
                      target_component=None):
    """Scenario labels are stored beside telemetry, never inside telemetry rows."""
    config = config or _config_for(seed)
    sim = MicrogridSimulator(config, seed)
    if nature == "fault":
        sim.inject(mode_kind(scenario_type), mode, severity, duration_ticks, start_tick)
    elif nature == "attack":
        target_component = target_component or _target_for(scenario_type, seed)
        sim.inject_attack(AttackType(scenario_type), target_component,
                          severity, duration_ticks, start_tick, StealthLevel(stealth_level))
    return SimulatedRun(run_id, seed, sim.run(ticks), nature, origin_layer, scenario_type,
                        mode, stealth_level, severity, start_tick, duration_ticks, config,
                        target_component)


def mode_kind(kind):
    from app.fault_injection import FaultKind
    return FaultKind(kind)


def _target_for(attack_type, seed):
    attack_type = AttackType(attack_type)
    return ATTACK_TARGETS[attack_type][seed % len(ATTACK_TARGETS[attack_type])]


def generate_runs(*, repeats=2, ticks=240, seed=72100,
                  severities=(0.25, 0.6, 1.0), stealth_levels=tuple(StealthLevel)):
    """Generate normal + every implemented fault mode and all eight attack types."""
    if type(repeats) is not int or repeats < 1 or ticks < 200:
        raise ValueError("repeats must be >=1 and ticks must be >=200")
    stealth_levels = tuple(StealthLevel(level) for level in stealth_levels)
    rng = random.Random(seed)
    runs, index = [], 0

    def add(**values):
        nonlocal index
        run_seed = seed + 1009 + index * 17
        if values["nature"] == "normal":
            start, duration = 0, 0
        else:
            start = rng.randint(25, min(85, ticks - 100))
            duration = min(rng.choice((55, 75, 95)), ticks - start - 1)
        values.pop("start_tick", None)
        values.pop("duration_ticks", None)
        run = simulate_scenario(f"stage-b-{index:05d}", run_seed, start_tick=start,
                                duration_ticks=duration, ticks=ticks, **values)
        runs.append(run)
        index += 1

    # Baseline runs are intentionally over-sampled: the anomaly detector only
    # produces a post-fire training window on its (rare) normal false alarms.
    for _ in range(max(12, repeats * 60)):
        add(nature="normal", scenario_type="normal", origin_layer=None,
            mode=None, stealth_level=None, severity=None, start_tick=0, duration_ticks=0)
    for kind, modes in MODES.items():
        for mode in sorted(modes):
            for severity in severities:
                for _ in range(repeats):
                    origin = {"firmware": "firmware_config", "inverter": "actuator_inverter"}.get(
                        kind.value, kind.value)
                    add(nature="fault", scenario_type=kind.value, mode=mode,
                        origin_layer=origin, severity=severity, stealth_level=None)
    for attack_type in AttackType:
        for level in stealth_levels:
            for severity in severities:
                for _ in range(repeats):
                    target = _target_for(attack_type.value, seed + 1009 + index * 17)
                    if attack_type is AttackType.MULTI_STAGE:
                        layer = "communication"
                    else:
                        layer = {"solar_sensor": "sensor", "battery_sensor": "sensor",
                                 "demand_sensor": "sensor", "communication": "communication",
                                 "controller": "controller", "firmware": "firmware_config",
                                 "inverter": "actuator_inverter"}[target]
                    add(nature="attack", scenario_type=attack_type.value, mode=None,
                        origin_layer=layer, stealth_level=level.value,
                        severity=severity, target_component=target)
    return runs


def detect_run(run: SimulatedRun, detector: AnomalyDetector, alert_policy: AlertPolicy | None = None):
    observations = FeatureExtractor(run.config).transform(run.telemetry)
    statuses = detector.predict(observations)
    if alert_policy is not None:
        first = _first_policy_fire(statuses, alert_policy)
        fires = [first] if first is not None else []
    else:
        fires = [result["tick"] for result in statuses if result["combined_status"] != "normal"]
    if run.nature != "normal":
        end_tick = run.start_tick + run.duration_ticks
        fires = [tick for tick in fires if run.start_tick <= tick < end_tick]
    return min(fires) if fires else None


def incident_sample(run: SimulatedRun, detector: AnomalyDetector, alert_policy: AlertPolicy | None = None):
    """One post-fire, causal window and evaluation metadata for a complete run."""
    fire_tick = detect_run(run, detector, alert_policy)
    if fire_tick is None:
        return None
    last_tick = len(run.telemetry) - 1
    if run.nature != "normal":
        last_tick = min(last_tick, run.start_tick + run.duration_ticks - 1)
    infer_tick = min(last_tick, fire_tick + WINDOW_TICKS - 1)
    rows = run.telemetry[fire_tick:infer_tick + 1]
    baseline_rows = run.telemetry[max(0, fire_tick - WINDOW_TICKS):fire_tick]
    feature_values = extract_window(rows, solar_capacity_kw=run.config.solar_capacity_kw,
                                    battery_capacity_kwh=run.config.battery_capacity_kwh,
                                    tick_seconds=run.config.tick_seconds,
                                    communication_delay_ticks=run.config.communication_delay_ticks,
                                    baseline_rows=baseline_rows)
    return {"run_id": run.run_id, "seed": run.seed, "features": feature_values,
            "nature": run.nature, "origin_layer": run.origin_layer,
            "scenario_type": run.scenario_type, "mode": run.mode,
            "stealth_level": run.stealth_level, "severity": run.severity,
            "start_tick": run.start_tick, "duration_ticks": run.duration_ticks,
            "detector_fire_tick": fire_tick, "inference_tick": infer_tick,
            "detection_delay_ticks": max(0, fire_tick - run.start_tick),
            "inference_delay_ticks": max(0, infer_tick - run.start_tick),
            "telemetry_window": rows}


def feature_frame(samples):
    rows = [{"run_id": item["run_id"], "seed": item["seed"], **item["features"],
             "nature": item["nature"], "origin_layer": item["origin_layer"],
             "scenario_type": item["scenario_type"], "mode": item["mode"],
             "stealth_level": item["stealth_level"], "severity": item["severity"],
             "detector_fire_tick": item["detector_fire_tick"],
             "inference_tick": item["inference_tick"],
             "detection_delay_ticks": item["detection_delay_ticks"]} for item in samples]
    return pd.DataFrame(rows, columns=["run_id", "seed", *FEATURE_NAMES, "nature",
                                      "origin_layer", "scenario_type", "mode", "stealth_level",
                                      "severity", "detector_fire_tick", "inference_tick",
                                      "detection_delay_ticks"])


def split_runs(runs, *, test_fraction=0.25, seed=42, held_out_stealth=None):
    """Partition complete runs; the generalization test holds out one whole stealth level."""
    if not 0 < test_fraction < 1 or not runs:
        raise ValueError("Require runs and test_fraction in (0, 1)")
    ids = [run.run_id for run in runs]
    seeds = [run.seed for run in runs]
    if len(set(ids)) != len(ids) or len(set(seeds)) != len(seeds):
        raise ValueError("Run IDs and seeds must be unique")
    rng = random.Random(seed)
    if held_out_stealth is None:
        groups = {}
        for run in runs:
            key = (run.nature, run.scenario_type, run.mode, run.stealth_level, run.severity)
            groups.setdefault(key, []).append(run)
        train, test = [], []
        for group in groups.values():
            group = list(group)
            rng.shuffle(group)
            n_test = max(1, round(len(group) * test_fraction)) if len(group) > 1 else 0
            test.extend(group[:n_test])
            train.extend(group[n_test:])
    else:
        train = [run for run in runs if run.stealth_level != held_out_stealth]
        test = [run for run in runs if run.stealth_level == held_out_stealth]
        # Add disjoint normal/fault examples to the generalization test.
        for nature in ("normal", "fault"):
            pool = [run for run in train if run.nature == nature]
            rng.shuffle(pool)
            n_test = max(1, round(len(pool) * test_fraction)) if len(pool) > 1 else 0
            chosen = set(run.run_id for run in pool[:n_test])
            test.extend(run for run in pool if run.run_id in chosen)
            train = [run for run in train if run.run_id not in chosen]
    if set(run.run_id for run in train) & set(run.run_id for run in test):
        raise ValueError("A complete run appears in both partitions")
    if set(run.seed for run in train) & set(run.seed for run in test):
        raise ValueError("A seed appears in both partitions")
    if held_out_stealth is not None and any(run.stealth_level == held_out_stealth for run in train):
        raise ValueError("Held-out stealth level leaked into training")
    return train, test


def write_dataset(runs, detector, csv_path, metadata_path, *, seed, config):
    samples, no_detection = [], []
    for run in runs:
        item = incident_sample(run, detector)
        if item is None:
            no_detection.append(run.manifest())
        else:
            samples.append(item)
    table = feature_frame(samples)
    csv_path, metadata_path = Path(csv_path), Path(metadata_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(csv_path, index=False)
    metadata = {"dataset": "synthetic simulation runs; observable telemetry only",
                "generator_seed": seed, "configuration": config,
                "feature_version": 1, "feature_names": list(FEATURE_NAMES),
                "window_ticks": WINDOW_TICKS,
                "window_rule": "first existing detector fire, then a causal window ending no later than fire+19; no future ticks",
                "run_count": len(runs), "detected_run_count": len(samples),
                "detector_miss_count": len(no_detection),
                "run_manifests": [run.manifest() for run in runs],
                "detector_misses": no_detection}
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return samples, metadata

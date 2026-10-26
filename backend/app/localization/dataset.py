"""Complete independently seeded runs; labels are targets, never input features."""
import random

import numpy as np
import pandas as pd

from app.detection.dataset import ScenarioRun, simulate_run, validate_partitions
from app.fault_injection import Fault
from app.fault_injection.engine import MODES
from .features import FEATURE_NAMES, LocalizationFeatureExtractor


CLASSES = ("normal", "sensor", "communication", "controller", "firmware", "inverter")
UNKNOWN = "unknown"
DISPLAY_NAMES = {"normal": "Normal", "sensor": "Sensor", "communication": "Communication",
                 "controller": "Controller", "firmware": "Firmware/Configuration",
                 "inverter": "Actuator/Inverter", "unknown": "Unknown or insufficient evidence"}


def partition_runs(partition: str, *, repeats: int | None = None, ticks: int = 360,
                   normal_count: int | None = None) -> list[ScenarioRun]:
    defaults = {"train": (100000, 3, 24), "validation": (200000, 1, 8), "test": (300000, 2, 8)}
    if partition not in defaults:
        raise ValueError("Use train, validation or test")
    base, default_repeats, default_normal = defaults[partition]
    repeats = default_repeats if repeats is None else repeats
    normal_count = default_normal if normal_count is None else normal_count
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("repeats must be an integer in [1, 10]")
    if type(normal_count) is not int or not 1 <= normal_count <= 100:
        raise ValueError("normal_count must be an integer in [1, 100]")
    if type(ticks) is not int or ticks < 240:
        raise ValueError("ticks must be an integer >= 240")
    runs = [simulate_run(f"source-{partition}-normal-{i}", base + i, ticks) for i in range(normal_count)]
    for kind, modes in MODES.items():
        for mode in sorted(modes):
            for severity in (0.25, 0.6, 1.0):
                for repeat in range(repeats):
                    seed = base + len(runs)
                    rng = random.Random(seed)
                    start = rng.randint(30, 65)
                    duration = rng.randint(100, min(170, ticks - start))
                    fault = Fault(kind, mode, start, duration, severity)
                    # Include weakly observable operating conditions in every partition.
                    hour = rng.choice([6, 10, 16, 20])
                    runs.append(simulate_run(f"source-{partition}-{kind.value}-{mode}-{severity}-{repeat}",
                                             seed, ticks, fault, start_hour=hour))
    return runs


def selected_observations(run: ScenarioRun):
    observations = LocalizationFeatureExtractor(run.config).transform(run.telemetry)
    if run.fault is None:
        return observations, "normal"
    active = [observation for observation in observations if run.fault.active(observation.tick)]
    if not active:
        raise ValueError("Fault run must contain an active fault interval")
    return active, run.fault.kind.value


def supervised_table(runs: list[ScenarioRun]):
    records = []
    for run in runs:
        observations, target = selected_observations(run)
        for observation in observations:
            records.append({"run_id": run.run_id, "tick": observation.tick,
                            **observation.features, "target": target})
    return pd.DataFrame(records, columns=["run_id", "tick", *FEATURE_NAMES, "target"])


def training_arrays(runs):
    if not runs:
        raise ValueError("Training runs are required")
    validate_partitions(runs)
    table = supervised_table(runs)
    if set(table["target"]) != set(CLASSES):
        raise ValueError("Training requires all six known source classes")
    values = table.loc[:, FEATURE_NAMES].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Features must be finite")
    return values, table["target"].to_numpy(), table

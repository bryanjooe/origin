"""Scenario-level partitions. Labels exist here only for evaluation bookkeeping."""
from dataclasses import asdict, dataclass
import random

import pandas as pd

from app.fault_injection import Fault
from app.fault_injection.engine import MODES
from app.simulator import GridConfig, MicrogridSimulator
from .features import FEATURE_NAMES, FeatureExtractor


@dataclass
class ScenarioRun:
    run_id: str
    seed: int
    config: GridConfig
    telemetry: list[dict]
    fault: Fault | None = None

    def observations(self):
        return FeatureExtractor(self.config).transform(self.telemetry)

    def manifest(self):
        return dict(run_id=self.run_id, seed=self.seed, config=asdict(self.config),
                    ticks=len(self.telemetry), fault=asdict(self.fault) if self.fault else None)


def simulate_run(run_id: str, seed: int, ticks: int = 1440,
                 fault: Fault | None = None, start_hour: float | None = None):
    rng = random.Random(seed)
    config = GridConfig(start_hour=rng.choice([0, 6, 10, 16, 20]) if start_hour is None else start_hour,
                        solar_capacity_kw=rng.uniform(10, 14), base_demand_kw=rng.uniform(6, 8),
                        battery_capacity_kwh=rng.uniform(20, 30), initial_soc_pct=rng.uniform(35, 85),
                        communication_delay_ticks=rng.choice([0, 0, 1]),
                        packet_loss_probability=rng.choice([0, 0.005]))
    sim = MicrogridSimulator(config, seed)
    if fault:
        sim.faults.schedule(fault)
    return ScenarioRun(run_id, seed, config, sim.run(ticks), fault)


def normal_runs(partition: str, count: int, ticks: int = 1440):
    bases = {"train": 1000, "calibration": 10000, "test": 20000}
    if partition not in bases or type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("Use train/calibration/test and 1..1000 complete runs")
    return [simulate_run(f"{partition}-{index}", bases[partition] + index, ticks)
            for index in range(count)]


def fault_runs(ticks: int = 360):
    runs = []
    for kind, modes in MODES.items():
        for mode in sorted(modes):
            for severity in (0.25, 0.6, 1.0):
                for repeat in range(2):
                    seed = 30000 + len(runs)
                    start = 40 + seed % 30
                    fault = Fault(kind, mode, start, 160, severity)
                    runs.append(simulate_run(f"fault-{seed}", seed, ticks, fault,
                                             start_hour=10 if repeat == 0 else 16))
    return runs


def feature_table(runs: list[ScenarioRun]):
    records = []
    for run in runs:
        for observation in run.observations():
            records.append({"run_id": run.run_id, "tick": observation.tick,
                            **observation.features})
    return pd.DataFrame(records, columns=["run_id", "tick", *FEATURE_NAMES])


def validate_partitions(*groups):
    ids, seeds = set(), set()
    for group in groups:
        for run in group:
            if run.run_id in ids or run.seed in seeds:
                raise ValueError("Partitions must have disjoint run IDs and random seeds")
            ids.add(run.run_id)
            seeds.add(run.seed)

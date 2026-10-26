"""Internal deterministic simulation branches; no inference or API endpoints."""
from .foundation import ComparisonFrame, ShadowBranch, SimulationSnapshot
from .experiments import ExperimentResult, Hypothesis, run_experiment
from .comparison import compare_hypotheses

__all__ = ["ComparisonFrame", "ExperimentResult", "Hypothesis", "ShadowBranch", "SimulationSnapshot", "compare_hypotheses", "run_experiment"]

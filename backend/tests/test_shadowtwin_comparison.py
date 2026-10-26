"""Evidence-based partial orders, uncertainty and independence from hidden labels."""
import asyncio
from copy import deepcopy
import json
import pickle

import pytest

from app.api.config import ServerSettings
from app.api.runtime import SimulationRuntime
from app.attack_injection import AttackEngine
from app.explainability.evidence import collect_evidence, observable_sample
from app.fault_injection import FaultEngine
from app.localization.features import LocalizationFeatureExtractor
from app.shadowtwin import Hypothesis, ShadowBranch, SimulationSnapshot, compare_hypotheses
from app.shadowtwin import comparison
from app.simulator import GridConfig, MicrogridSimulator


def source(kind="controller"):
    sim = MicrogridSimulator(GridConfig(start_hour=17, communication_delay_ticks=3), seed=42)
    if kind == "controller":
        sim.inject_attack("controller_compromise", "controller", severity=0.8, duration_ticks=80)
    elif kind == "sensor_fault":
        sim.inject("sensor", "bias", severity=0.8, duration_ticks=80)
    elif kind == "sensor_attack":
        sim.inject_attack("sensor_spoof", "solar_sensor", severity=0.8, stealth_level="naive", duration_ticks=80)
    elif kind == "inverter":
        sim.inject("inverter", "shutdown", duration_ticks=80)
    elif kind == "replay":
        sim.inject_attack("replay", "communication", start_tick=5, duration_ticks=80)
    sim.run(10)
    return sim


def hypotheses():
    return [Hypothesis("C", "controller", "command inconsistency", "restore_controller_policy", duration_ticks=40),
            Hypothesis("S", "solar_sensor", "measurement inconsistency", "use_redundant_solar", duration_ticks=10)]


def by_id(result, ident):
    return next(item for item in result["hypotheses"] if item["hypothesis_id"] == ident)


def test_comparison_ranks_measured_command_improvement_from_fair_common_conditions():
    sim, requested = source(), hypotheses()
    snapshot = SimulationSnapshot(sim)
    before = pickle.dumps((sim, snapshot._simulator, snapshot._ledger))
    result = compare_hypotheses(snapshot, requested, 20)
    assert result["status"] == "Ranked prospective evidence"
    assert result["historical_source"] == "Not established"
    assert result["hypothesis_ranking"][0]["hypothesis_ids"] == ["C"]
    a, b = by_id(result, "C"), by_id(result, "S")
    assert a["experiment"]["control_telemetry"] == b["experiment"]["control_telemetry"]
    assert {x["experiment"]["start_tick"] for x in result["hypotheses"]} == {10}
    assert {x["experiment"]["end_tick"] for x in result["hypotheses"]} == {30}
    assert requested[0].duration_ticks == 40 and requested[1].duration_ticks == 10
    observation = a["physical_observations"]["controller_policy_residual"]
    assert observation["control_mean_excess"] > 0 and observation["experimental_mean_excess"] == 0
    assert observation["relative_reduction"] == 1
    assert a["evidence_assessment"] == "Stronger relative evidence support"
    assert b["evidence_assessment"] != "Stronger relative evidence support"
    assert pickle.dumps((sim, snapshot._simulator, snapshot._ledger)) == before
    json.dumps(result, allow_nan=False)


def test_wrong_interventions_without_relevant_improvement_remain_inconclusive():
    result = compare_hypotheses(SimulationSnapshot(source("inverter")), hypotheses(), 20)
    assert result["status"] == "Inconclusive" and result["hypothesis_ranking"] == []
    assert all(item["ranking_position"] is None for item in result["hypotheses"])
    assert all(item["evidence_assessment"] != "Stronger relative evidence support" for item in result["hypotheses"])
    assert all(row["inverter_actual_kw"] == 0 for row in by_id(result, "C")["experiment"]["experimental_telemetry"])


def test_negative_communication_outcome_is_not_called_successful():
    requested = hypotheses()[:1] + [Hypothesis("L", "communication", "packet manipulation", "flush_communication")]
    result = compare_hypotheses(SimulationSnapshot(source("replay")), requested, 20)
    link = by_id(result, "L")
    assert link["delivered_energy_difference_kwh"] < 0
    assert "Worsened" in link["intervention_outcome"]
    assert "temporary" in link["explanation"]
    assert link["evidence_assessment"] != "Stronger relative evidence support"
    assert result["status"] == "Inconclusive"


def test_large_actual_energy_gain_cannot_distinguish_fault_from_spoofing():
    requested = [Hypothesis("fault", "solar_sensor", "sensor malfunction", "use_redundant_solar"),
                 Hypothesis("spoof", "solar_sensor", "sensor spoofing", "use_redundant_solar")]
    a = compare_hypotheses(SimulationSnapshot(source("sensor_fault")), requested, 20)
    b = compare_hypotheses(SimulationSnapshot(source("sensor_attack")), requested, 20)
    assert a == b
    assert all(item["delivered_energy_difference_kwh"] > 1 for item in a["hypotheses"])
    assert a["status"] == "Inconclusive"
    assert a["hypothesis_ranking"][0]["hypothesis_ids"] == ["fault", "spoof"]
    assert a["hypothesis_ranking"][0]["relationship"] == "equivalent"
    assert a["tied_or_tradeoff_groups"] == [["fault", "spoof"]]


def test_energy_values_never_break_a_residual_tie(monkeypatch):
    requested = [Hypothesis("A", "solar_sensor", "malfunction", "use_redundant_solar"),
                 Hypothesis("B", "solar_sensor", "manipulation", "use_redundant_solar")]
    run = comparison.run_experiment
    def energy_context_only(snapshot, hypothesis, **kwargs):
        result = run(snapshot, hypothesis, **kwargs)
        if hypothesis.hypothesis_id == "B":
            # Unit input perturbation to prove energy is not a hidden weight.
            # No simulator outputs or persisted demonstration reports are changed.
            result.energy["experimental_minus_control"]["delivered_kwh"] += 100
        return result
    monkeypatch.setattr(comparison, "run_experiment", energy_context_only)
    result = compare_hypotheses(SimulationSnapshot(source("sensor_fault")), requested, 20)
    assert by_id(result, "B")["delivered_energy_difference_kwh"] > by_id(result, "A")["delivered_energy_difference_kwh"]
    assert result["status"] == "Inconclusive"
    assert result["hypothesis_ranking"][0]["hypothesis_ids"] == ["A", "B"]


def test_unsupported_alternative_is_untested_not_zero_scored_or_disproved():
    requested = [hypotheses()[0], Hypothesis("U", "inverter", "inverter mechanism", "repair_inverter")]
    result = compare_hypotheses(SimulationSnapshot(source()), requested, 20)
    unsupported = by_id(result, "U")
    assert unsupported["experiment_status"] == "unsupported"
    assert unsupported["ranking_position"] is None and unsupported["intervention_rank"] is None
    assert unsupported["delivered_energy_difference_kwh"] is None and unsupported["physical_observations"] == {}
    assert result["status"] == "Inconclusive" and result["hypothesis_ranking"] == []
    assert by_id(result, "C")["evidence_assessment"] == "Partial evidence support"


def test_normal_operation_without_abnormal_evidence_does_not_force_rankings():
    result = compare_hypotheses(SimulationSnapshot(source("normal")), hypotheses(), 20)
    assert result["status"] == "Inconclusive" and result["hypothesis_ranking"] == []
    assert any("No above-threshold" in reason for reason in result["inconclusive_reasons"])


def test_missing_measurements_are_excluded_without_manufacturing_residuals(monkeypatch):
    run = comparison.run_experiment
    def missing(snapshot, hypothesis, **kwargs):
        result = run(snapshot, hypothesis, **kwargs)
        result.control_telemetry[0].pop("controller_command_kw")
        return result
    monkeypatch.setattr(comparison, "run_experiment", missing)
    result = compare_hypotheses(SimulationSnapshot(source()), hypotheses(), 20)
    assert result["status"] == "Inconclusive"
    assert all(not item["eligible_for_ranking"] and item["physical_observations"] == {} for item in result["hypotheses"])
    assert result["intervention_ranking"] == []


def test_unknown_ai_predictions_remain_separate_and_do_not_prevent_measured_comparisons():
    evidence = {"diagnosis": {"source": "unknown", "source_model_available": True},
                "security_attribution": {"available": True, "origin": "Unknown", "nature": "Undetermined"}}
    original = deepcopy(evidence)
    result = compare_hypotheses(SimulationSnapshot(source()), hypotheses(), 20, evidence)
    assert result["status"] == "Ranked prospective evidence"
    assert result["independent_model_evidence"]["stage_b"]["prediction"] == "Unknown"
    assert result["independent_model_evidence"]["stage_b"]["nature"] == "Undetermined"
    assert evidence == original


def test_independent_disagreeing_model_score_is_context_not_a_probability_or_winner():
    evidence = {"diagnosis": {"source": "sensor", "source_model_available": True, "confidence": 0.99,
                "candidates": [{"source": "sensor", "confidence": 0.99}]}}
    result = compare_hypotheses(SimulationSnapshot(source()), hypotheses(), 20, evidence)
    assert result["hypothesis_ranking"][0]["hypothesis_ids"] == ["C"]
    assert result["status"] == "Inconclusive"
    assert by_id(result, "C")["model_agreement"]["phase1"] == "different_candidate_group"
    assert "conflict remains unresolved" in by_id(result, "C")["explanation"]
    assert result["independent_model_evidence"]["phase1"]["model_score"] == 0.99


def test_real_recorded_evidence_links_are_retained_but_future_or_hidden_fields_are_not():
    sim = source()
    observations = LocalizationFeatureExtractor(sim.config).transform(sim.history)
    records = collect_evidence(observable_sample(sim.history[-1]), {"residual_checks": observations[-1].evidence}, None)
    future = {**records[0], "tick": 10, "id": f"t10:{records[0]['signal']}"}
    records[0]["sample"]["ground_truth"] = "SECRET_LABEL"
    records.append(future)
    result = compare_hypotheses(SimulationSnapshot(sim), hypotheses(), 20, {"evidence": records})
    ids = by_id(result, "C")["recorded_evidence_ids"]
    assert "t9:controller_policy_residual" in ids
    assert all(item["id"] in {record["id"] for record in records} for item in result["recorded_evidence"])
    assert all(item["tick"] < result["start_tick"] for item in result["recorded_evidence"])
    assert "SECRET_LABEL" not in json.dumps(result)


def test_hidden_evaluation_metadata_and_schedule_labels_cannot_change_ranking(monkeypatch):
    sim = source()
    original = compare_hypotheses(SimulationSnapshot(sim), hypotheses(), 20)
    sim.attacks._records[0].update(attack_type="SECRET_FAMILY", target_component="SECRET_SOURCE")
    sim.evaluation_only_origin = "SECRET_ANSWER"
    def forbidden(*args):
        raise AssertionError("Hidden schedule labels inspected")
    monkeypatch.setattr(AttackEngine, "ground_truth", forbidden)
    monkeypatch.setattr(FaultEngine, "ground_truth", forbidden)
    changed = compare_hypotheses(SimulationSnapshot(sim), hypotheses(), 20,
        {"ground_truth": {"source": "SECRET_ANSWER"}, "evaluation_correctness": True})
    assert changed == original
    assert "SECRET_" not in json.dumps(changed)


def test_repeated_comparison_and_caller_order_do_not_break_ties_or_determinism():
    snapshot = SimulationSnapshot(source())
    a = compare_hypotheses(snapshot, hypotheses(), 20)
    b = compare_hypotheses(snapshot, list(reversed(hypotheses())), 20)
    assert a == b


def test_tolerance_boundary_cycles_remain_ambiguous_and_bounded():
    # Arithmetic unit case, not fabricated simulator/evaluation output.
    vectors = [(0, 0.75e-9, 1.5e-9), (1.5e-9, 0, 0.75e-9), (0.75e-9, 1.5e-9, 0)]
    items = [{"hypothesis_id": str(i), "_after": {str(j): {"normalized_excess": x} for j, x in enumerate(v)}} for i, v in enumerate(vectors)]
    fronts = comparison._pareto(items, ["0", "1", "2"])
    assert len(fronts) == 1 and len(fronts[0]) == 3


def test_inconsistent_energy_accounting_is_not_ranked(monkeypatch):
    run = comparison.run_experiment
    def invalid_ledger(snapshot, hypothesis, **kwargs):
        result = run(snapshot, hypothesis, **kwargs)
        result.energy["experimental"]["energy_balance_residual_kwh"] = 0.01
        return result
    monkeypatch.setattr(comparison, "run_experiment", invalid_ledger)
    result = compare_hypotheses(SimulationSnapshot(source()), hypotheses(), 20)
    assert result["status"] == "Inconclusive" and result["hypothesis_ranking"] == []
    assert all("conservation tolerance" in item["exclusion_reason"] for item in result["hypotheses"])


def test_unmatched_randomness_excludes_experiments_from_ranking(monkeypatch):
    advance = ShadowBranch.advance
    def changed_draws(branch, ticks, **kwargs):
        if kwargs:
            branch._simulator._weather.random()
        return advance(branch, ticks, **kwargs)
    monkeypatch.setattr(ShadowBranch, "advance", changed_draws)
    result = compare_hypotheses(SimulationSnapshot(source()), hypotheses(), 20)
    assert result["status"] == "Inconclusive" and result["hypothesis_ranking"] == []
    assert all(not item["eligible_for_ranking"] for item in result["hypotheses"])


def test_mixed_initial_conditions_cannot_rank_even_when_individual_pairs_match(monkeypatch):
    other = MicrogridSimulator(GridConfig(start_hour=17, communication_delay_ticks=3), seed=73)
    other.inject_attack("controller_compromise", "controller", severity=0.8, duration_ticks=80)
    other.run(10)
    alternate = SimulationSnapshot(other)
    run = comparison.run_experiment
    def wrong_checkpoint(snapshot, hypothesis, **kwargs):
        return run(alternate if hypothesis.hypothesis_id == "S" else snapshot, hypothesis, **kwargs)
    monkeypatch.setattr(comparison, "run_experiment", wrong_checkpoint)
    result = compare_hypotheses(SimulationSnapshot(source()), hypotheses(), 20)
    assert result["status"] == "Inconclusive" and result["hypothesis_ranking"] == []
    assert all("Control branches differ" in item["exclusion_reason"] for item in result["hypotheses"])


def test_failed_experiment_cannot_receive_a_numeric_rank(monkeypatch):
    def failure(*args, **kwargs):
        raise RuntimeError("SECRET_INTERNAL_DETAIL")
    monkeypatch.setattr(comparison, "run_experiment", failure)
    result = compare_hypotheses(SimulationSnapshot(source()), hypotheses(), 20)
    assert all(item["experiment_status"] == "failed" and item["ranking_position"] is None for item in result["hypotheses"])
    assert "SECRET_INTERNAL_DETAIL" not in json.dumps(result)


def test_explanations_quote_the_actual_rule_excess_and_energy_outcomes():
    result = compare_hypotheses(SimulationSnapshot(source()), hypotheses(), 20)
    item = by_id(result, "C")
    metric = item["physical_observations"]["controller_policy_residual"]
    assert f"{metric['control_mean_excess']:.6g} to {metric['experimental_mean_excess']:.6g} kW" in item["explanation"]
    assert f"{item['delivered_energy_difference_kwh']:+.6g} kWh" in item["explanation"]
    assert "not proof" in item["explanation"]


@pytest.mark.parametrize("duration", [True, 0, -1, 1.5, 1001, 121])
def test_invalid_duration_or_work_budget_rejected_before_running(duration, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Experiment should not start")
    monkeypatch.setattr(comparison, "run_experiment", forbidden)
    with pytest.raises(ValueError):
        compare_hypotheses(SimulationSnapshot(source()), hypotheses(), duration)


def test_horizon_duplicate_ids_and_batch_size_limits():
    snapshot = SimulationSnapshot(source(), max_tick=20)
    with pytest.raises(ValueError, match="horizon"):
        compare_hypotheses(snapshot, hypotheses(), 11)
    with pytest.raises(ValueError, match="unique"):
        compare_hypotheses(snapshot, [hypotheses()[0]] * 2, 1)
    with pytest.raises(ValueError, match="2 to"):
        compare_hypotheses(snapshot, [hypotheses()[0]] * 7, 1)


def test_comparison_does_not_modify_live_runtime_ledgers_or_history():
    async def scenario():
        runtime = SimulationRuntime(ServerSettings(database_path=":memory:", anomaly_model=None, source_model=None, security_model=None))
        try:
            await runtime.step(10)
            snapshot = await runtime.shadow_snapshot()
            before = pickle.dumps((runtime.sim, runtime.baseline, runtime.uncorrected, runtime.ledgers, snapshot._simulator))
            database = list(runtime.store.connection.iterdump())
            compare_hypotheses(snapshot, hypotheses(), 20)
            assert pickle.dumps((runtime.sim, runtime.baseline, runtime.uncorrected, runtime.ledgers, snapshot._simulator)) == before
            assert list(runtime.store.connection.iterdump()) == database
        finally:
            await runtime.close()
    asyncio.run(scenario())

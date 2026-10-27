"""Planning policy, chronology, ground-truth exclusion and ShadowTwin compatibility."""
from copy import deepcopy
from dataclasses import replace
import json
import pickle

import pytest

from app.investigation_agent import (ObservableContext, Observation, PlanningBudget,
                                     observable_context, plan_investigation)
from app.shadowtwin import Hypothesis, SimulationSnapshot
from app.shadowtwin.experiments import SUPPORTED_INTERVENTIONS
from app.simulator import MicrogridSimulator


def state(*signals, tick=20, status="warning"):
    return {"run_id": "current-run", "next_tick": tick, "runtime_error": None,
        "telemetry": {"tick": tick - 1},
        "anomaly": {"tick": tick - 1, "combined_status": status, "residual_checks": [
            {"signal": signal, "value": 8.0, "threshold": 5.0, "unit": "reported unit"} for signal in signals]}}


def plan(*signals, **kwargs):
    return plan_investigation(observable_context(state(*signals)), **kwargs)


def selected(result):
    return [item["intervention_id"] for item in result["selected_experiments"]]


@pytest.mark.parametrize("signal, intervention", [
    ("solar_measurement_residual", "use_redundant_solar"),
    ("controller_policy_residual", "restore_controller_policy"),
    ("stale_telemetry", "flush_communication"),
])
def test_adaptive_observed_residual_selection(signal, intervention):
    result = plan(signal)
    assert result["status"] == "ready"
    assert selected(result) == [intervention]
    item = result["selected_experiments"][0]
    assert signal in item["selection_reason"]
    assert "8" in item["selection_reason"] and "5" in item["selection_reason"]
    assert item["observed_abnormalities"][0]["tick"] == 19
    assert item["observed_abnormalities"][0]["evidence_id"] is None  # Never fabricate persisted IDs.
    assert item["diagnostic_purpose"] and item["limitations"]
    assert item["estimated_branch_ticks"] == 40
    json.dumps(result, allow_nan=False)


def test_multiple_candidates_keep_equal_priority_and_defer_under_budget():
    result = plan("solar_measurement_residual", "controller_policy_residual")
    assert result["equal_priority_groups"] == [["restore_controller_policy", "use_redundant_solar"]]
    assert len(result["selected_experiments"]) == 1
    assert "Equal evidential priority" in result["alternative_investigations"][0]["deferral_reason"]
    assert result["alternative_investigations"][0]["possible_next_action"] is True
    assert len(plan("solar_measurement_residual", "controller_policy_residual", budget=PlanningBudget(max_experiments=3))["selected_experiments"]) == 2


def test_more_distinct_rule_evidence_has_transparent_priority_not_a_fixed_order():
    result = plan("stale_telemetry", "packet_local_solar_disagreement", "solar_measurement_residual")
    # Two distinct rules support both pathways: the tie remains explicit.
    assert result["equal_priority_groups"] == [["flush_communication", "use_redundant_solar"]]
    controller = plan("controller_policy_residual", "stale_telemetry")
    assert controller["equal_priority_groups"]
    assert selected(plan("controller_policy_residual")) != selected(plan("solar_measurement_residual"))


def test_unknown_and_undetermined_do_not_block_evidence_or_become_attack_claims():
    raw = state("solar_measurement_residual")
    incident = {"id": "incident-1", "run_id": "current-run", "first_observed_tick": 19, "last_alert_tick": 19,
        "security_attribution": {"available": True, "window_end_tick": 19, "origin": "Unknown", "nature_verdict": "Undetermined"}}
    result = plan_investigation(observable_context(raw, incident))
    assert result["status"] == "ready" and selected(result) == ["use_redundant_solar"]
    assert result["context"]["current_model_context"]["stage_b_origin"] == "Unknown"
    assert result["context"]["current_model_context"]["stage_b_nature"] == "Undetermined"


def test_equivalent_explanations_share_one_mechanism_and_retain_ambiguity():
    result = plan("solar_measurement_residual", available_interventions=["use_redundant_solar"] * 2)
    assert len(result["selected_experiments"]) == 1
    item = result["selected_experiments"][0]
    assert {hypothesis["hypothesis_id"] for hypothesis in item["related_hypotheses"]} == {"solar_fault", "solar_manipulation"}
    assert any("cannot independently distinguish" in text for text in item["limitations"])
    assert result["budget"]["planned_branch_ticks"] == 40


def test_current_model_corroboration_is_only_a_tie_break_and_keeps_sensor_group():
    raw = state("solar_measurement_residual", "controller_policy_residual")
    raw.update(source={"tick": 19, "predicted_source": "controller", "confidence": .7}, models={"source": {"available": True}})
    result = plan_investigation(observable_context(raw))
    assert selected(result) == ["restore_controller_policy"]
    assert result["selected_experiments"][0]["priority_basis"]["current_model_corroboration"] == ["phase1"]
    stronger = state("solar_measurement_residual", "controller_policy_residual", "packet_local_solar_disagreement")
    stronger.update(source=raw["source"], models=raw["models"])
    assert selected(plan_investigation(observable_context(stronger))) == ["use_redundant_solar"]
    incident = {"id":"i", "run_id":"current-run", "security_attribution": {"available":True,"window_end_tick":19,"origin":"Sensor","nature_verdict":"Undetermined"}}
    assert observable_context(raw, incident).stage_b_components == ("solar_sensor", "battery_sensor", "demand_sensor")


def test_missing_evidence_and_anomaly_only_do_not_manufacture_source():
    for raw in ({}, {"next_tick":20}, state()):
        result = plan_investigation(observable_context(raw))
        assert result["status"] == "insufficient_evidence"
        assert selected(result) == []


def test_normal_current_state_has_no_unnecessary_experiment():
    result = plan_investigation(observable_context(state(status="normal")))
    assert result["status"] == "no_relevant_current_abnormality" and selected(result) == []


def test_historical_evidence_is_not_current_and_other_run_ticks_are_independent():
    incident = {"id":"old-incident", "run_id":"old-run", "first_observed_tick":600, "last_alert_tick":800,
        "evidence":[{"id":"t800:solar_measurement_residual","tick":800,"signal":"solar_measurement_residual","value":8,"threshold":5,"unit":"kW"}]}
    result = plan_investigation(observable_context(state(status="normal"), incident))
    assert result["status"] == "no_relevant_current_abnormality"
    assert "historical_incident_current_state_only" in result["uncertainty"]["limitations"]
    assert result["context"]["evidence_availability"]["historical_observations"] == 1
    assert result["context"]["evidence_availability"]["current_observations"] == 0
    assert selected(result) == []
    incident["run_id"] = "current-run"
    incident["evidence"][0].update(tick=5, id="t5:solar_measurement_residual")
    incident.update(first_observed_tick=5,last_alert_tick=5)
    assert plan_investigation(observable_context(state(status="normal"), incident))["status"] == "no_relevant_current_abnormality"


def test_historical_incident_can_coexist_with_different_current_abnormality():
    incident = {"id":"old", "run_id":"old-run", "first_observed_tick":60,"last_alert_tick":80}
    result = plan_investigation(observable_context(state("controller_policy_residual",tick=800),incident))
    assert selected(result) == ["restore_controller_policy"]
    assert "historical_incident_current_state_only" in result["uncertainty"]["limitations"]


def test_mandatory_hidden_label_invariance_and_no_input_mutation():
    a={"system_state":state("solar_measurement_residual"),"incident":{"id":"i","run_id":"current-run"},"ground_truth":"controller"}
    b=deepcopy(a)
    for record in (a["system_state"], a["system_state"]["telemetry"], a["system_state"]["anomaly"], a["incident"]):
        record.update(ground_truth="firmware",actual_attack_type="replay",target_component="communication",training_labels=["controller"],_schedule=["hidden-a"])
    for record in (b["system_state"], b["system_state"]["telemetry"], b["system_state"]["anomaly"], b["incident"]):
        record.update(ground_truth="inverter",actual_attack_type="sensor_spoof",target_component="solar_sensor",training_labels=["sensor"],_schedule=["hidden-b"])
    before=deepcopy(a)
    assert plan_investigation(a) == plan_investigation(b)
    assert a == before
    encoded=json.dumps(plan_investigation(a))
    assert all(key not in encoded for key in ("ground_truth","target_component","actual_attack_type","training_labels","_schedule","hidden-a"))


def test_unsupported_capabilities_and_observations_are_not_executable():
    result=plan("solar_measurement_residual",available_interventions=["repair_inverter"])
    assert result["status"] == "unsupported" and selected(result) == []
    assert result["uncertainty"]["unsupported_interventions"] == ["repair_inverter"]
    assert plan("inverter_output_residual")["status"] == "unsupported"
    assert plan("solar_measurement_residual",available_interventions={"use_redundant_solar":"controller"})["status"] == "unsupported"


@pytest.mark.parametrize("budget", [PlanningBudget(max_candidates=0),PlanningBudget(max_experiments=0),PlanningBudget(max_branch_ticks=39)])
def test_planning_budget_exhaustion(budget):
    result=plan("controller_policy_residual",budget=budget)
    assert result["status"] == "budget_exhausted" and selected(result) == []


def test_candidate_experiment_work_and_horizon_limits():
    result=plan("solar_measurement_residual","controller_policy_residual","stale_telemetry",budget=PlanningBudget(max_candidates=2,max_experiments=3,max_branch_ticks=80))
    assert len(selected(result)) == 2 and result["budget"]["planned_branch_ticks"] == 80
    assert len(set(selected(result))) == len(selected(result))
    assert plan_investigation(observable_context(state("stale_telemetry",tick=9990)))["status"] == "budget_exhausted"


@pytest.mark.parametrize("kwargs",[{"max_candidates":4},{"max_experiments":4},{"duration_ticks":True},{"duration_ticks":0},{"duration_ticks":1001},{"max_branch_ticks":481}])
def test_invalid_budget_rejected(kwargs):
    with pytest.raises(ValueError): PlanningBudget(**kwargs)


def test_determinism_and_input_order_do_not_inflate_evidence():
    raw=state("stale_telemetry","controller_policy_residual")
    first=plan_investigation(observable_context(raw),list(SUPPORTED_INTERVENTIONS))
    raw["anomaly"]["residual_checks"].reverse()
    raw["anomaly"]["residual_checks"] *= 3
    second=plan_investigation(observable_context(raw),list(reversed(SUPPORTED_INTERVENTIONS)))
    assert first == second


def test_observable_log_flags_are_useful_without_model_and_zero_flags_are_not():
    raw=state()
    raw["telemetry"]["security_telemetry"]={"duplicate_sequence":True,"solar_sensors_agree":True,"command_policy_consistent":True}
    result=plan_investigation(observable_context(raw))
    assert selected(result) == ["flush_communication"]
    assert "temporary" in result["selected_experiments"][0]["limitations"][0]
    raw["telemetry"]["security_telemetry"]["duplicate_sequence"]=False
    assert selected(plan_investigation(observable_context(raw))) == []


def test_stale_undated_and_nonfinite_evidence_not_promoted_to_current():
    raw=state("solar_measurement_residual")
    raw["anomaly"]["tick"]=5
    context=observable_context(raw)
    assert plan_investigation(context)["status"] == "insufficient_evidence"
    raw["anomaly"]["tick"]=19
    raw["anomaly"]["residual_checks"][0]["value"]=float("nan")
    assert selected(plan_investigation(observable_context(raw))) == []
    raw["anomaly"]["residual_checks"]=[{"signal":"controller_policy_residual","tick":4,"value":8,"threshold":5}]
    assert selected(plan_investigation(observable_context(raw))) == []


def test_only_existing_current_incident_evidence_can_link_persisted_ids():
    incident={"id":"i", "run_id":"current-run", "evidence":[{"id":"t19:solar_measurement_residual", "tick":19,"signal":"solar_measurement_residual","value":8,"threshold":5,"unit":"kW"}]}
    result=plan_investigation(observable_context(state(),incident))
    assert result["selected_experiments"][0]["observed_abnormalities"][0]["evidence_id"] == "t19:solar_measurement_residual"
    incident["evidence"][0]["id"]="invented-label"
    assert selected(plan_investigation(observable_context(state(),incident))) == []


def test_planning_never_reads_snapshot_or_advances_simulation(monkeypatch):
    sim=MicrogridSimulator(seed=42)
    snapshot=SimulationSnapshot(sim)
    before=pickle.dumps(sim)
    for obj in (sim,snapshot):
        with pytest.raises(TypeError): plan_investigation(obj)
        with pytest.raises(TypeError): observable_context(obj)
    def forbidden(*args,**kwargs): raise AssertionError("Planning must not execute simulations")
    monkeypatch.setattr(MicrogridSimulator,"step",forbidden)
    monkeypatch.setattr("app.shadowtwin.experiments.run_experiment",forbidden)
    result=plan("controller_policy_residual")
    assert pickle.dumps(sim)==before
    item=result["selected_experiments"][0]
    hypothesis=Hypothesis(**item["hypothesis"],duration_ticks=item["duration_ticks"])
    assert SUPPORTED_INTERVENTIONS[hypothesis.intervention] == hypothesis.component
    assert result["context"]["snapshot_captured"] is False


def test_approved_context_is_immutable_and_rejects_undated_current_evidence():
    context=observable_context(state("solar_measurement_residual"))
    with pytest.raises(ValueError): replace(context,current_tick=40)
    with pytest.raises(ValueError): replace(context,phase1_components=("controller",))
    assert type(context) is ObservableContext


def test_old_records_without_an_incident_window_still_warn_about_prospective_scope():
    incident={"id":"i", "run_id":"current-run", "evidence":[{"id":"t5:solar_measurement_residual", "tick":5,"signal":"solar_measurement_residual","value":8,"threshold":5,"unit":"kW"}]}
    result=plan_investigation(observable_context(state(status="normal"),incident))
    assert result["status"] == "no_relevant_current_abnormality"
    assert "historical_incident_current_state_only" in result["uncertainty"]["limitations"]
    assert "incident_timing_unknown" in result["uncertainty"]["limitations"]


def test_no_future_action_claim_when_horizon_or_current_state_prevents_capture():
    result=plan_investigation(observable_context(state("controller_policy_residual",tick=9999)))
    assert not result["alternative_investigations"][0]["possible_next_action"]
    raw=state("controller_policy_residual")
    raw["runtime_error"]="Recorded runtime failure"
    unavailable=plan_investigation(observable_context(raw))
    assert unavailable["status"] == "insufficient_evidence" and selected(unavailable) == []
    assert not unavailable["alternative_investigations"][0]["possible_next_action"]

"""Genuine isolated experiments plus bounded failure-contract fixtures."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
import json
import pickle

import pytest

from app.api.config import ServerSettings
from app.api.runtime import SimulationRuntime
from app.detection import FeatureExtractor
from app.investigation_agent import (PlanningBudget, SnapshotReference, observable_context,
    capture_investigation_inputs, run_autonomous_investigation)
from app.investigation_agent import orchestrator
from app.schemas.api import AttackRequest
from app.shadowtwin import Hypothesis, SimulationSnapshot, run_experiment, compare_hypotheses
from app.shadowtwin.comparison import assess_experiments
from app.shadowtwin.experiments import ExperimentResult
from app.simulator import GridConfig, MicrogridSimulator


def fixture(kind="controller", *, solar_duration=80, controller_duration=80):
    sim=MicrogridSimulator(GridConfig(start_hour=17,communication_delay_ticks=3),seed=42)
    if kind in ("sensor","ambiguous"):
        sim.inject("sensor","bias",severity=.8,duration_ticks=solar_duration)
    if kind in ("controller","ambiguous"):
        sim.inject_attack("controller_compromise","controller",severity=.8,duration_ticks=controller_duration)
    if kind=="communication":
        sim.inject_attack("replay","communication",start_tick=5,severity=.8,duration_ticks=80)
    extractor=FeatureExtractor(sim.config)
    for _ in range(10):
        row=sim.step(); observed=extractor.update(row)
    state={"run_id":"run1","next_tick":sim.tick,"telemetry":row,
        "anomaly":{"tick":row["tick"],"residual_checks":observed.residual_checks}}
    context=observable_context(state)
    reference=SnapshotReference(SimulationSnapshot(sim),"run1","run1:10")
    return sim,state,context,reference


def run(kind="controller",**kwargs):
    sim,state,context,reference=fixture(kind,**kwargs)
    return run_autonomous_investigation(context,reference)


def mechanisms(report): return [step["intervention_id"] for step in report["steps"]]


@pytest.mark.parametrize("kind,mechanism",[("controller","restore_controller_policy"),("sensor","use_redundant_solar"),("communication","flush_communication")])
def test_genuine_adaptive_first_selection_and_measured_experiment(kind,mechanism):
    report=run(kind)
    assert mechanisms(report)==[mechanism]
    assert report["executed_experiments"]==1 and report["branch_ticks_charged"]==40
    step=report["steps"][0]
    assert step["start_tick"]==10 and step["end_tick"]==30
    assert len(step["paired_telemetry"])==len(step["measurement_differences"])==20
    assert step["decision_afterward"]["action"]=="stop"
    json.dumps(report,allow_nan=False)


def test_controller_actual_residual_and_energy_improvement():
    report=run()
    step=report["steps"][0]
    measurement=step["physical_observations"]["controller_policy_residual"]
    assert measurement["control_mean_excess"]>0 and measurement["experimental_mean_excess"]==0
    assert step["delivered_energy_difference_kwh"]==pytest.approx(.768)
    assert report["final_assessment"]["intervention_effectiveness"]=="Intervention supported"
    assert report["final_assessment"]["source_evidence_assessment"]=="Inconclusive"
    assert report["final_assessment"]["most_useful_tested_intervention"] is None
    assert report["comparison"]["hypothesis_ranking"]==[]


def test_result_dependent_followup_with_identical_initial_observations_and_real_outcomes():
    # The same fault is observable through tick 9 in both cases. Only its future
    # duration differs; the decision cannot inspect those hidden schedules.
    _,_,short_context,short_ref=fixture("ambiguous",solar_duration=10)
    _,_,long_context,long_ref=fixture("ambiguous",solar_duration=80)
    assert short_context==long_context
    short=run_autonomous_investigation(short_context,short_ref)
    long=run_autonomous_investigation(long_context,long_ref)
    assert mechanisms(short)==["restore_controller_policy"]
    assert mechanisms(long)==["restore_controller_policy","use_redundant_solar"]
    assert short["steps"][0]["decision_afterward"]["action"]=="stop"
    assert long["steps"][0]["decision_afterward"]["action"]=="continue"
    assert long["steps"][0]["decision_afterward"]["next_intervention"]=="use_redundant_solar"


def test_sensor_explanations_remain_ambiguous_and_are_not_duplicate_experiments():
    report=run("sensor")
    assert report["attempted_experiments"]==1
    assert {h["hypothesis_id"] for h in report["steps"][0]["related_hypotheses"]}=={"solar_fault","solar_manipulation"}
    assert report["final_assessment"]["source_evidence_assessment"]=="Inconclusive"
    assert report["final_assessment"]["additional_independent_evidence_required"] is True


def test_ineffective_window_does_not_reject_or_confirm_historical_source():
    report=run("controller",controller_duration=10)
    assert report["steps"][0]["intervention_outcome"]=="No relevant symptom improvement"
    assert report["steps"][0]["delivered_energy_difference_kwh"]==pytest.approx(0)
    assert report["stopping_reason"]=="no_relevant_comparison_abnormality"
    assert report["final_assessment"]["historical_source"]=="Not established"


def test_negative_communication_energy_not_success_or_attack_removal():
    report=run("communication")
    assert report["steps"][0]["delivered_energy_difference_kwh"]<0
    assert report["final_assessment"]["intervention_effectiveness"]=="Mixed evidence"
    assert any("ongoing" in limitation for limitation in report["evidence_fusion"]["limitations"])
    assert report["final_assessment"]["malicious_intent"]=="Not established"


def test_multiple_results_reuse_comparison_without_rerunning_simulation(monkeypatch):
    calls=[]
    actual=orchestrator.run_experiment
    def track(*args,**kwargs):
        calls.append(args[1].intervention)
        return actual(*args,**kwargs)
    monkeypatch.setattr(orchestrator,"run_experiment",track)
    def forbidden(*args,**kwargs): raise AssertionError("Cached comparison must not run experiments")
    monkeypatch.setattr("app.shadowtwin.comparison.run_experiment",forbidden)
    report=run("ambiguous")
    assert len(calls)==len(set(calls))==report["attempted_experiments"]==2
    assert report["comparison"]["intervention_ranking"]
    assert report["branch_ticks_charged"]==80
    assert all(step["start_tick"]==10 and step["end_tick"]==30 for step in report["steps"])


def test_cached_analysis_matches_original_batch_semantics_exactly():
    _,_,context,ref=fixture("ambiguous")
    hypotheses=[Hypothesis("controller","controller","Possible command inconsistency","restore_controller_policy",checkpoint_id=ref.reference_id),
        Hypothesis("solar","solar_sensor","Possible measurement inconsistency","use_redundant_solar",checkpoint_id=ref.reference_id)]
    original=compare_hypotheses(ref.snapshot,hypotheses,20,comparison_id="same")
    cached={h.hypothesis_id:run_experiment(ref.snapshot,replace(h,duration_ticks=20),experiment_id=f"same:{h.hypothesis_id}") for h in hypotheses}
    reused=assess_experiments(ref.snapshot,hypotheses,cached,20,comparison_id="same")
    assert original==reused


def test_initial_predictions_candidates_and_experiment_findings_remain_separate():
    _,raw,_,ref=fixture()
    raw["source"]={"tick":9,"predicted_source":"unknown","confidence":.57,"candidates":[{"source":"controller","confidence":.57}]}
    raw["models"]={"source":{"available":True}}
    incident={"id":"i","run_id":"run1","first_observed_tick":8,"last_alert_tick":9,
        "security_attribution":{"available":True,"window_end_tick":9,"origin":"Unknown","nature_verdict":"Undetermined","origin_confidence":.42,"nature_confidence":.51}}
    context=observable_context(raw,incident)
    before=deepcopy(context)
    report=run_autonomous_investigation(context,ref)
    originals={record["model"]:record for record in report["initial_ai_assessment"]["original_model_records"]}
    assert originals["phase1"]["original_fields"]["confidence"]==.57
    assert originals["phase1"]["reported_candidates"]==[{"label":"controller","model_score":.57}]
    assert originals["stage_b"]["original_fields"]["nature_verdict"]=="Undetermined"
    assert report["initial_ai_assessment"]["stage_b_origin"]=="Unknown"
    assert report["evidence_fusion"]["experimental_findings"]
    assert context==before
    assert "confidence" not in report["final_assessment"]


def test_correlated_duplicate_views_do_not_inflate_final_assessment():
    _,raw,context,ref=fixture()
    incident={"id":"i","run_id":"run1","evidence":[{"id":"t9:controller_policy_residual","tick":9,"signal":"controller_policy_residual","value":next(o.value for o in context.current_observations if o.signal=="controller_policy_residual"),"threshold":.1,"unit":"kW"}]}
    incident["evidence"]*=3
    duplicated=observable_context(raw,incident)
    first=run_autonomous_investigation(context,ref)
    second=run_autonomous_investigation(duplicated,ref)
    assert mechanisms(first)==mechanisms(second)
    assert first["final_assessment"]==second["final_assessment"]
    groups=second["evidence_fusion"]["initial_observable_evidence"]
    rule=next(item for item in groups if item["signal"]=="controller_policy_residual")
    assert sorted(rule["provenance"])==["current_detection","incident_record"]
    assert any("not independent" in text for text in second["evidence_fusion"]["limitations"])


@pytest.mark.parametrize("status",["insufficient_evidence","no_relevant_current_abnormality","unsupported","budget_exhausted"])
def test_nonready_planner_status_never_forces_experiment(status,monkeypatch):
    _,raw,_,ref=fixture()
    budget=None; capabilities=None
    if status=="insufficient_evidence": raw.pop("anomaly");raw["telemetry"]={"tick":9}
    elif status=="no_relevant_current_abnormality": raw["anomaly"]={"tick":9,"combined_status":"normal","residual_checks":[]};raw["telemetry"]={"tick":9}
    elif status=="unsupported": capabilities=["not_a_supported_intervention"]
    else: budget=PlanningBudget(max_experiments=0)
    def forbidden(*args,**kwargs): raise AssertionError("Must not execute")
    monkeypatch.setattr(orchestrator,"run_experiment",forbidden)
    report=run_autonomous_investigation(observable_context(raw),ref,budget,available_interventions=capabilities)
    assert report["status"]==status and report["attempted_experiments"]==0


def test_historical_incident_is_not_replayed_or_reinjected():
    _,raw,_,ref=fixture("normal")
    raw["anomaly"]={"tick":9,"combined_status":"normal","residual_checks":[]}
    incident={"id":"old","run_id":"old-run","first_observed_tick":57,"last_alert_tick":82,
        "evidence":[{"id":"t60:controller_policy_residual","tick":60,"signal":"controller_policy_residual","value":8,"threshold":.1,"unit":"kW"}]}
    report=run_autonomous_investigation(observable_context(raw,incident),ref)
    assert report["attempted_experiments"]==0
    assert "historical_incident_current_state_only" in report["evidence_fusion"]["limitations"]
    assert report["snapshot_tick"]==10


def test_ground_truth_metadata_changes_do_not_change_reports_or_choices():
    sim,raw,_,ref=fixture()
    clean=run_autonomous_investigation(observable_context(raw),ref)
    dirty=deepcopy(raw)
    for record in (dirty,dirty["telemetry"],dirty["anomaly"]):
        record.update(ground_truth="inverter",target_component="firmware",training_labels=["communication"],_schedule=["hidden"])
    altered=deepcopy(ref.snapshot)
    altered._simulator.hidden_source_label="a different hidden answer"
    second=run_autonomous_investigation(observable_context(dirty),SnapshotReference(altered,"run1","run1:10"))
    assert clean==second
    assert all(key not in json.dumps(second) for key in ("ground_truth","target_component","training_labels","_schedule","hidden_source_label"))


def test_live_branches_snapshot_schedules_history_and_ledgers_are_unchanged():
    async def scenario():
        runtime=SimulationRuntime(ServerSettings(database_path=":memory:",anomaly_model=None,source_model=None,security_model=None))
        try:
            await runtime.reset(config=GridConfig(start_hour=17,communication_delay_ticks=3))
            await runtime.inject_attack(AttackRequest(attack_type="controller_compromise",target_component="controller",severity=.8,duration_ticks=80))
            await runtime.step(10)
            context,ref=await capture_investigation_inputs(runtime)
            before=pickle.dumps((runtime.sim,runtime.baseline,runtime.uncorrected,runtime.ledgers,ref.snapshot))
            database=list(runtime.store.connection.iterdump())
            report=run_autonomous_investigation(context,ref)
            assert report["attempted_experiments"]==1
            assert pickle.dumps((runtime.sim,runtime.baseline,runtime.uncorrected,runtime.ledgers,ref.snapshot))==before
            assert list(runtime.store.connection.iterdump())==database
        finally: await runtime.close()
    asyncio.run(scenario())


def test_determinism_and_no_equivalent_repetition():
    sim,_,context,ref=fixture("ambiguous")
    before=pickle.dumps((sim,ref.snapshot))
    first=run_autonomous_investigation(context,ref)
    assert first==run_autonomous_investigation(context,ref)
    assert pickle.dumps((sim,ref.snapshot))==before
    assert len(mechanisms(first))==len(set(mechanisms(first)))


@pytest.mark.parametrize("budget",[PlanningBudget(max_experiments=1),PlanningBudget(max_branch_ticks=40),PlanningBudget(max_candidates=1)])
def test_count_candidate_and_work_budgets_are_hard_bounds(budget):
    _,_,context,ref=fixture("ambiguous")
    report=run_autonomous_investigation(context,ref,budget)
    assert len(report["steps"])<=min(budget.max_experiments,budget.max_candidates)
    assert report["branch_ticks_charged"]<=budget.max_branch_ticks
    assert report["attempted_experiments"]==1
    assert report["stopping_reason"]=="budget_exhausted"


def test_checkpoint_horizon_and_stale_identity_are_validated_without_execution():
    sim,raw,context,ref=fixture()
    limited=SnapshotReference(SimulationSnapshot(sim,max_tick=15),"run1","short")
    report=run_autonomous_investigation(context,limited)
    assert report["status"]=="budget_exhausted" and report["attempted_experiments"]==0
    with pytest.raises(ValueError):run_autonomous_investigation(context,SnapshotReference(ref.snapshot,"other","other:10"))
    raw["next_tick"]=11;raw["anomaly"]["tick"]=10;raw["telemetry"]["tick"]=10
    with pytest.raises(ValueError):run_autonomous_investigation(observable_context(raw),ref)
    with pytest.raises(TypeError):run_autonomous_investigation(context,ref.snapshot)


@pytest.mark.parametrize("status",["unsupported","invalid","failed"])
def test_failure_contract_is_safe_and_never_invents_measurements(status,monkeypatch):
    def failure(snapshot,hypothesis,*,experiment_id):
        return ExperimentResult(experiment_id,hypothesis.hypothesis_id,hypothesis.component,hypothesis.mechanism,hypothesis.intervention,hypothesis.checkpoint_id,status=status,reason="Controlled failure-contract fixture")
    monkeypatch.setattr(orchestrator,"run_experiment",failure)
    report=run()
    assert report["status"]=="failed" and report["attempted_experiments"]==1
    assert report["steps"][0]["paired_telemetry"]==[]
    assert report["steps"][0]["delivered_energy_difference_kwh"] is None
    assert report["final_assessment"]["most_useful_tested_intervention"] is None


def test_failed_first_test_can_select_a_genuine_supported_alternative(monkeypatch):
    actual=orchestrator.run_experiment
    calls=[]
    def failure_once(snapshot,hypothesis,*,experiment_id):
        calls.append(hypothesis.intervention)
        if len(calls)==1: raise RuntimeError("Controlled execution failure")
        return actual(snapshot,hypothesis,experiment_id=experiment_id)
    monkeypatch.setattr(orchestrator,"run_experiment",failure_once)
    report=run("ambiguous")
    assert calls==["restore_controller_policy","use_redundant_solar"]
    assert report["steps"][0]["decision_afterward"]["action"]=="continue"
    assert report["steps"][1]["execution_status"]=="completed"
    assert report["attempted_experiments"]==2


def test_corrupt_result_identity_is_rejected_without_reexecution(monkeypatch):
    actual=orchestrator.run_experiment
    calls=[]
    def corrupt(*args,**kwargs):
        calls.append(1);result=actual(*args,**kwargs);result.checkpoint_id="wrong";return result
    monkeypatch.setattr(orchestrator,"run_experiment",corrupt)
    report=run()
    assert len(calls)==1 and report["status"]=="failed"
    assert report["steps"][0]["execution_status"]=="invalid"
    assert report["steps"][0]["paired_telemetry"]==[]


def test_incompatible_controls_are_not_ranked(monkeypatch):
    actual=orchestrator.run_experiment
    calls=[]
    def changed_control(*args,**kwargs):
        result=actual(*args,**kwargs);calls.append(1)
        if len(calls)==2: result.control_telemetry[0]["demand_kw"]+=.01
        return result
    monkeypatch.setattr(orchestrator,"run_experiment",changed_control)
    report=run("ambiguous")
    assert report["comparison"]["hypothesis_ranking"]==[]
    assert report["comparison"]["intervention_ranking"]==[]
    assert all(not step["comparable"] for step in report["steps"])


def test_repeat_guard_stops_a_bad_planner_without_retry(monkeypatch):
    actual=orchestrator.plan_investigation
    saved=[]
    def repeating(*args,**kwargs):
        if not saved:saved.append(actual(*args,**kwargs))
        return deepcopy(saved[0])
    monkeypatch.setattr(orchestrator,"plan_investigation",repeating)
    report=run()
    assert report["stopping_reason"]=="repeated_experiment_prevented"
    assert report["attempted_experiments"]==1


def test_report_actual_differences_match_executed_observations():
    report=run()
    step=report["steps"][0]
    pair=step["paired_telemetry"][0]
    delta=step["measurement_differences"][0]["experimental_minus_control"]
    assert delta["delivered_kw"]==pytest.approx(pair["experimental"]["delivered_kw"]-pair["control"]["delivered_kw"])
    assert step["physical_observations"]==report["comparison"]["hypotheses"][0]["physical_observations"]
    assert report["initial_plan"]["selected_experiments"][0]["selection_reason"]==step["selection_reason"]
    json.dumps(report,allow_nan=False)


@pytest.mark.parametrize("change",["energy","row"])
def test_malformed_cached_measurements_fail_safely(change,monkeypatch):
    actual=orchestrator.run_experiment
    def malformed(*args,**kwargs):
        result=actual(*args,**kwargs)
        if change=="energy": result.energy={"control":None}
        else: result.control_telemetry[0]=None
        return result
    monkeypatch.setattr(orchestrator,"run_experiment",malformed)
    report=run()
    assert report["status"]=="failed"
    assert report["steps"][0]["paired_telemetry"]==[]
    assert report["final_assessment"]["source_evidence_assessment"]=="Inconclusive"



def test_hidden_labels_in_experimental_records_are_not_fused_or_exposed(monkeypatch):
    baseline=run()
    actual=orchestrator.run_experiment
    def labeled(*args,**kwargs):
        result=actual(*args,**kwargs)
        for row in [*result.control_telemetry,*result.experimental_telemetry]:
            row["ground_truth"]="different hidden answer"
            row["target_component"]="firmware"
            row["security_telemetry"]["training_labels"]=["hidden"]
        result.energy["ground_truth"]="another hidden answer"
        return result
    monkeypatch.setattr(orchestrator,"run_experiment",labeled)
    assert run()==baseline

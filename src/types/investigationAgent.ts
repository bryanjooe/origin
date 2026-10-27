import type { ShadowIncidentContext } from './shadowtwin'
export type AgentIncident = ShadowIncidentContext
export interface AgentEvidence { signal: string; tick: number; value: number | boolean; threshold: number | null; unit: string | null; evidence_ids: string[]; provenance: string[] }
export interface AgentStep {
  step: number; experiment_id: string; intervention_id: string; selection_reason: string
  related_hypotheses: {hypothesis_id:string; explanation:string}[]
  execution_status:string; start_tick:number|null; end_tick:number|null; comparable:boolean; exclusion_reason:string|null
  intervention_outcome:string; delivered_energy_difference_kwh:number|null
  physical_observations: Record<string,{unit:string;control_mean_excess:number;experimental_mean_excess:number}>
  relevant_evidence:AgentEvidence[]; limitations:string[]
  decision_afterward:{action:string;reason:string;explanation:string;next_intervention:string|null;remaining_original_targets:string[]}
  paired_telemetry:{tick:number;control:Record<string,number|null>;experimental:Record<string,number|null>}[]
}
export interface AgentReport {
  investigation_id:string; incident_id:string|null; run_id:string; snapshot_tick:number; status:string
  stopping_reason:string;stopping_explanation:string;executed_experiments:number;attempted_experiments:number;branch_ticks_charged:number
  budget:{duration_ticks:number;max_experiments:number;max_branch_ticks:number};steps:AgentStep[]
  initial_plan:{context:{incident_observation_window:{run_id:string|null;start_tick:number|null;end_tick:number|null}}}
  initial_ai_assessment:{anomaly_status:string|null;phase1_prediction:string|null;stage_b_origin:string|null;stage_b_nature:string|null;
    original_model_records:{model:string;scope:string;original_fields:Record<string,string|number|boolean|null>;reported_candidates:{label:string;model_score:number}[]}[]}
  final_assessment:{most_useful_tested_intervention:string|null;intervention_effectiveness:string;source_evidence_assessment:string;historical_source:string;malicious_intent:string;reason:string;additional_independent_evidence_required:boolean}
  evidence_fusion:{limitations:string[];unresolved_hypotheses:{hypothesis_id:string;explanation:string}[]}
  recommended_next_actions:string[]
}
export interface AgentJob {
  id:string;trigger:string;run_id:string;incident_id:string|null;snapshot_tick:number|null;status:string;stage:string
  created_at:string;finished_at:string|null;completed_experiments:number;report_available:boolean;stale:boolean;current_run_id:string
  reason:string|null;error:string|null;events?:{stage:string;intervention_id?:string;step?:number;reason?:string}[]
  progress_steps?:AgentStep[];report?:AgentReport|null
}
export interface AgentStatus {automatic_enabled:boolean;current_run_id:string;active:AgentJob|null;latest:AgentJob|null;recent:AgentJob[];retention:number;lifecycle:string}

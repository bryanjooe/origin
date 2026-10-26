export type ShadowIntervention = 'use_redundant_solar' | 'restore_controller_policy' | 'flush_communication'
export interface ShadowHypothesis {
  hypothesis_id: string
  component: 'solar_sensor' | 'controller' | 'communication'
  mechanism: string
  intervention: ShadowIntervention
}
export interface ShadowRequest {
  hypotheses: ShadowHypothesis[]
  duration_ticks: number
  incident_id?: string
  expected_run_id: string
}
export interface ShadowRow {
  tick: number
  elapsed_seconds?: number | null
  actual_solar_kw?: number | null
  measured_solar_kw?: number | null
  redundant_solar_kw?: number | null
  inverter_actual_kw?: number | null
  inverter_requested_kw?: number | null
  delivered_kw?: number | null
  battery_soc_pct?: number | null
}
export interface ShadowHypothesisResult {
  hypothesis_id: string
  suspected_component: string
  proposed_mechanism: string
  intervention: string
  experiment_status: string
  ranking_position: number | null
  intervention_rank: number | null
  evidence_assessment: string
  intervention_outcome: string
  delivered_energy_difference_kwh: number | null
  exclusion_reason?: string | null
  explanation: string
  warnings: string[]
  physical_observations: Record<string, {unit: string; control_mean_excess: number; experimental_mean_excess: number}>
  experiment: null | {
    start_tick: number | null
    end_tick: number | null
    execution_tick: number | null
    intervention_status: string
    sustained: boolean
    control_telemetry: ShadowRow[]
    experimental_telemetry: ShadowRow[]
    warnings: string[]
    limitations: string[]
  }
}
export interface ShadowComparison {
  comparison_id: string
  run_id: string
  current_run_id: string
  run_changed: boolean
  snapshot_tick: number
  start_tick: number
  end_tick: number
  incident_id: string | null
  incident_run_id: string | null
  historical_incident: boolean
  status: string
  historical_source: string
  hypotheses: ShadowHypothesisResult[]
  hypothesis_ranking: {position: number; hypothesis_ids: string[]; relationship: string}[]
  intervention_ranking: {position: number; hypothesis_ids: string[]; relationship: string}[]
  tied_or_tradeoff_groups: string[][]
  inconclusive_reasons: string[]
  limitations: string[]
  independent_model_evidence?: Record<string, {prediction: string | null; nature?: string | null; available: boolean}>
}

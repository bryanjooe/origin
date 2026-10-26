export type Severity = 'normal' | 'warning' | 'critical' | 'unknown'

export type SimulationStatus = 'running' | 'paused' | 'stopped' | 'idle' | 'unknown'

export interface HealthResponse {
  status?: string
  backend?: string | { status?: string; message?: string }
  model?: string | { status?: string; trained?: boolean; version?: string }
  model_status?: string
  message?: string
}

export interface MetricValues {
  solar_generation_kw?: number
  solar_generation_kwh?: number
  battery_soc_pct?: number
  demand_kw?: number
  energy_delivered_kwh?: number
  renewable_utilization_pct?: number
  unmet_demand_kwh?: number
  active_incidents?: number
  [key: string]: number | undefined
}

export interface SystemState {
  run_id?: string
  status?: string
  simulation_status?: string
  simulation_time?: string | number
  simulation_time_seconds?: number
  sim_time_seconds?: number
  next_tick?: number
  anomaly_status?: string
  anomaly?: { status?: string; score?: number; source?: string }
  model_status?: string
  backend_status?: string
  metrics?: MetricValues
  components?: ComponentStatus[]
  active_incidents?: number
}

export interface TopologyNode {
  id: string
  label?: string
  type?: string
  status?: string
  telemetry?: Record<string, unknown>
  events?: EventRecord[]
  candidate_source?: boolean
  security_candidate?: boolean
  observed_symptom?: boolean
  security_observed?: boolean
  potentially_affected?: boolean
  security_potentially_affected?: boolean
  direct_evidence?: EvidenceItem[]
  security_observations?: AttributionObservation[]
  downstream_dependencies?: string[]
  [key: string]: unknown
}

export interface TopologyEdge {
  id?: string
  source: string
  target: string
  kind?: string
  type?: string
  suspected?: boolean
  security_suspected?: boolean
  label?: string
  [key: string]: unknown
}

export interface TopologyResponse {
  nodes: TopologyNode[]
  edges?: TopologyEdge[]
}

export interface TelemetryPoint {
  tick?: number
  timestamp?: string
  time?: string
  simulation_time?: string | number
  simulation_time_seconds?: number
  solar_generation_kw?: number
  actual_solar_kw?: number
  demand_kw?: number
  delivered_kw?: number
  energy_delivered_kw?: number
  battery_soc_pct?: number
  battery_power_kw?: number
  anomaly_score?: number
  [key: string]: string | number | boolean | null | undefined
}

export interface TelemetryBatch {
  run_id: string
  items: TelemetryPoint[]
  next_after_tick: number
}

export interface EventRecord {
  id?: string | number
  timestamp?: string
  time?: string
  simulation_time?: string | number
  severity?: string
  type?: string
  event?: string
  message?: string
  description?: string
  details?: Record<string, unknown>
  tick?: number
  elapsed_seconds?: number
  nodes?: string[]
  evidence_id?: string
  signal?: string
}

export interface PredictionCandidate {
  source?: string
  component?: string
  confidence?: number
  score?: number
}

export interface EvidenceItem {
  id?: string | number
  type?: string
  source?: string
  description?: string
  value?: unknown
  timestamp?: string
  tick?: number
  signal?: string
  nodes?: string[]
  threshold?: number
  unit?: string
}

export interface IncidentSummary {
  id: string | number
  title?: string
  status?: string
  severity?: string
  source?: string
  predicted_source?: string | null
  confidence?: number | null
  anomaly_score?: number | null
  timestamp?: string
  started_at?: string
  ground_truth?: { source?: string; fault?: string; label?: string } | null
}

export interface IncidentDetail extends IncidentSummary {
  graph?: IncidentGraph
  summary?: string
  candidates?: PredictionCandidate[]
  evidence?: EvidenceItem[]
  timeline?: EventRecord[]
  affected_components?: string[]
  diagnostic_checks?: string[]
  residual_checks?: EvidenceItem[]
  security_attribution?: SecurityAttribution
}

export interface AttributionObservation {
  name: string
  value: string | number
  unit?: string
  window_ticks?: number
  category?: string
  interpretation?: string
}

export interface SecurityAttribution {
  available: boolean
  model_available?: boolean
  status?: 'pending' | 'available' | 'unavailable' | 'insufficient_evidence'
  confidence_kind?: string
  window_complete?: boolean
  required_window_ticks?: number
  window_start_tick?: number
  window_end_tick?: number | null
  detector_fire_tick?: number
  uncertainty?: string
  nature_verdict: string
  nature_confidence?: number | null
  nature_candidates?: Array<{ nature: string; confidence: number }>
  origin?: string
  origin_confidence?: number | null
  origin_candidates?: Array<{ layer: string; confidence: number }>
  evidence?: {
    points_toward_attack?: AttributionObservation[]
    points_toward_fault?: AttributionObservation[]
    ambiguous?: AttributionObservation[]
    statement?: string
    uncertainty?: string | null
  }
  reason?: string
  inference_tick?: number
  window_ticks?: number
}

export interface SecurityClassMetric {
  precision?: number
  recall?: number
  'f1-score'?: number
  support?: number
}

export interface SecurityTaskReport {
  count?: number
  accuracy?: number
  macro_f1?: number
  per_class?: Record<string, SecurityClassMetric>
  confusion_matrix?: { labels: string[]; counts: number[][] }
}

export interface SecurityProtocolReport {
  nature?: SecurityTaskReport
  fault_vs_attack?: SecurityTaskReport
  origin?: SecurityTaskReport
  detector_coverage?: number
  attack_detection_delay_ticks?: { mean?: number }
  abstention_rate?: { nature?: number; origin?: number }
  nature_probability_calibration?: { brier_score?: number; expected_calibration_error?: number }
  nature_feature_importance_by_stealth?: Record<string, Array<{ feature: string; importance: number }>>
  model_selection?: { selected?: string; validation_macro_f1?: Record<string, number> }
  nature_recall_by_stealth?: Record<string, { attack_label_rate?: number; detector_fire_rate?: number; run_count?: number }>
  nature_recall_by_attack_type?: Record<string, { attack_label_rate?: number; detector_fire_rate?: number; run_count?: number }>
  fault_only_origin_comparison?: {
    existing_source_classifier?: { macro_f1_including_unknown?: number; coverage?: number; evaluated_fault_runs?: number }
    new_origin_layer_classifier?: { macro_f1_including_unknown?: number; coverage?: number; evaluated_fault_runs?: number }
  }
  normal_run_false_positive_rate?: { detector_fire?: number; nature_classifier_attack_label?: number; normal_run_count?: number }
  validation_alert_calibration?: { validation_normal_false_alert_rate?: number; validation_event_coverage?: number; selection_rule?: string }
}

export interface SecurityMetrics {
  available: boolean
  provenance?: string
  run_count?: number
  class_run_counts?: Record<string, number>
  held_out?: SecurityProtocolReport
  stealth_generalization?: SecurityProtocolReport
  model_error?: string | null
  results_error?: string
  confidence_kind?: string | null
  calibration_note?: string | null
}

export interface IncidentGraph {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  affected_downstream?: string[]
  suspected_paths?: { nodes: string[]; evidence_ids: string[]; interpretation: string }[]
  security_paths?: { nodes: string[]; evidence_ids: string[]; interpretation: string }[]
  security_candidate_nodes?: string[]
  observed_nodes?: string[]
  potentially_affected_nodes?: string[]
  limitations?: string[]
  evidence_limitations?: string[]
  security_origin_message?: string
  security_status?: string
}

export interface ComponentStatus {
  id: string
  name?: string
  component?: string
  status?: string
  severity?: string
  telemetry?: Record<string, unknown>
  events?: EventRecord[]
}

export interface SustainabilityMetric {
  value?: number | null
  unit?: string
  estimated?: boolean
  label?: string
}

export interface SustainabilityComparison {
  normal?: Record<string, number | null>
  faulty?: Record<string, number | null>
  after_correction?: Record<string, number | null>
}

export interface SustainabilityResponse {
  generated_kwh?: number | null
  delivered_kwh?: number | null
  curtailed_kwh?: number | null
  demand_served_pct?: number | null
  unmet_demand_kwh?: number | null
  battery_efficiency_pct?: number | null
  estimated_loss_kwh?: number | null
  metrics?: Record<string, SustainabilityMetric | number | null>
  comparison?: SustainabilityComparison
  assumptions?: string[]
}

export interface ClassMetric {
  label: string
  precision?: number | null
  recall?: number | null
  f1?: number | null
  support?: number | null
}

export interface ModelMetrics {
  trained?: boolean
  model_status?: string
  dataset_size?: number | null
  train_scenario_count?: number | null
  test_scenario_count?: number | null
  accuracy?: number | null
  per_class?: ClassMetric[]
  confusion_matrix?: { labels: string[]; values: number[][] }
  anomaly_detector?: {
    precision?: number | null
    recall?: number | null
    f1?: number | null
    false_positive_rate?: number | null
    detection_delay_seconds?: number | null
  }
  by_severity?: Array<{ severity: string; accuracy?: number | null; recall?: number | null }>
  evaluation_status?: string
  false_positive_rate?: number
}

export interface SimulationActionResponse {
  status?: string
  message?: string
  simulation_status?: string
  simulation_time?: string | number
  scheduled?: { start_tick?: number; duration_ticks?: number }
}

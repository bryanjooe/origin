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
  status?: string
  simulation_status?: string
  simulation_time?: string | number
  simulation_time_seconds?: number
  sim_time_seconds?: number
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
  [key: string]: unknown
}

export interface TopologyEdge {
  id?: string
  source: string
  target: string
  kind?: string
  type?: string
  suspected?: boolean
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
  summary?: string
  candidates?: PredictionCandidate[]
  evidence?: EvidenceItem[]
  timeline?: EventRecord[]
  affected_components?: string[]
  diagnostic_checks?: string[]
  residual_checks?: EvidenceItem[]
}

export interface IncidentGraph {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
  affected_downstream?: string[]
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
}

export interface SimulationActionResponse {
  status?: string
  message?: string
  simulation_status?: string
  simulation_time?: string | number
}

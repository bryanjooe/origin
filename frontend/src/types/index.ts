export type Status = 'normal' | 'warning' | 'critical'
export type Source = 'normal' | 'sensor' | 'communication' | 'controller' | 'firmware' | 'inverter' | 'unknown'
export interface Availability { available: boolean; error: string | null }
export interface GridConfig { tick_seconds: number; start_hour: number; solar_capacity_kw: number; battery_capacity_kwh: number; initial_soc_pct: number; [key: string]: number }
export interface Telemetry {
  tick: number; elapsed_seconds: number; irradiance: number; expected_solar_kw: number; actual_solar_kw: number;
  measured_solar_kw: number; measured_soc_pct: number; battery_soc_pct: number; battery_power_kw: number;
  demand_kw: number; delivered_kw: number; unmet_demand_kw: number; controller_command_kw: number;
  inverter_requested_kw: number; inverter_actual_kw: number; message_age_seconds: number | null;
  config_integrity_ok: boolean; [key: string]: unknown
}
export interface Residual { signal: string; value: number; threshold: number; unit: string; method: string }
export interface Anomaly { tick: number; anomaly_score: number; ml_status: Status; rule_status: Status; combined_status: Status; warning_threshold: number; critical_threshold: number; residual_checks: Residual[] }
export interface Candidate { source: Source; label: string; confidence: number }
export interface SourcePrediction { predicted_source: Source; confidence: number | null; top_candidate: Candidate; candidates: Candidate[]; abstention_reasons: string[] }
export interface State { run_id: string; running: boolean; next_tick: number; simulated_seconds: number; speed_ticks_per_second: number; telemetry: Telemetry | null; anomaly: Anomaly | null; source: SourcePrediction | null; config: GridConfig; models: { anomaly: Availability; source: Availability }; runtime_error: string | null }
export interface TelemetryPoint { telemetry: Telemetry; anomaly: Anomaly | null; source: SourcePrediction | null }
export interface Diagnosis { source: Source; model_predicted_source: Source | null; confidence: number | null; candidates: Candidate[]; reasons: string[]; source_model_available: boolean }
export interface IncidentSummary { id: string; run_id: string; local_id: string; status: 'open' | 'resolved' | 'interrupted'; severity: Status; detection_tick: number; detection_time_seconds: number; confirmation_delay_seconds: number; as_of_tick: number; diagnosis: Diagnosis; created_at: string }
export interface Evidence { id: string; tick: number; elapsed_seconds: number; signal: string; nodes: string[]; value: number; threshold: number; unit: string; kind: string; sample: Record<string, unknown> }
export interface TimelineEvent { tick: number; elapsed_seconds: number; event: string; signal?: string; source?: Source; nodes: string[]; evidence_id?: string }
export interface GraphNode { id: string; label: string; candidate_source?: boolean; observed_symptom?: boolean; potentially_affected?: boolean; evidence_ids?: string[]; telemetry?: Record<string, unknown>[]; events?: TimelineEvent[] }
export interface GraphEdge { source: string; target: string; kind: string; dependency: string; suspected: boolean; evidence_ids?: string[]; evidence_scope?: string; uncertainty?: string | null }
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[]; limitations?: string[]; potentially_affected_nodes?: string[] }
export interface Incident extends IncidentSummary {
  first_observed_tick: number; representative_tick: number; peak_anomaly_score: number; resolved_at_tick: number | null;
  graph: GraphData; evidence: Evidence[]; timeline: TimelineEvent[]; latest_diagnosis: Diagnosis;
  explanation: { why_flagged: string[]; likely_source: string; deviations: { evidence_id: string; text: string }[]; alternative_sources: Candidate[]; diagnostic_checks: string[]; uncertainty: string[]; recovery: string; potentially_affected_components: string[] }
}
export interface IncidentList { items: IncidentSummary[]; total: number; limit: number; offset: number }
export interface SystemEvent { id: number; tick: number; run_id: string; event: string; created_at: string }
export interface Ledger { ticks: number; solar_generated_kwh: number; renewable_delivered_kwh: number; delivered_kwh: number; demand_kwh: number; unmet_demand_kwh: number; unused_dc_kwh: number; solar_curtailed_kwh: number; battery_energy_kwh: number; battery_loss_kwh: number; inverter_loss_kwh: number; energy_balance_residual_kwh: number; renewable_energy_balance_residual_kwh: number; observed_charge_efficiency: number | null; observed_discharge_efficiency: number | null; configured_round_trip_efficiency: number; solar_capture_fraction: number | null; renewable_delivery_fraction_of_generated: number | null; initial_unknown_battery_energy_kwh: number }
export interface Sustainability { run_id: string; comparison: { baseline: Ledger; faulty_uncorrected: Ledger; operated: Ledger }; estimated_fault_delivery_loss_kwh: number; estimated_correction_delivery_gain_kwh: number; correction_ticks: number[]; assumptions: string[] }
export interface FaultSpec { kind: Exclude<Source, 'normal' | 'unknown'>; mode: string; severity: number; duration_ticks: number; start_tick?: number; cancelled_at_tick?: number | null }
export interface Scenario { id: string; status: string; metadata: { seed: number; next_tick: number; ground_truth: { label: string; faults: FaultSpec[] }; correction_ticks: number[] } }
export interface BinaryMetrics { precision: number; recall: number; f1: number; false_positive_rate: number | null; true_positive: number; false_positive: number; true_negative: number; false_negative: number; detected_fault_runs: number; total_fault_runs: number; mean_detection_delay_seconds: number | null; roc_auc?: number }
export interface AnomalyReport { training_rows?: number; normal_rows: number; fault_rows: number; normal_run_count: number; fault_run_count: number; performance: { ml: BinaryMetrics; rules: BinaryMetrics; combined: BinaryMetrics } }
export interface ClassMetric { precision: number; recall: number; 'f1-score': number; support: number }
export interface SourceReport { rows: number; run_count: number; normal_runs: number; fault_runs: number; raw_accuracy: number; accuracy_including_unknown: number; coverage: number; accepted_accuracy: number | null; unknown_rate: number; macro_f1: number; per_class: Record<string, ClassMetric>; confusion_matrix: { labels: string[]; counts: number[][] }; mean_first_correct_delay_seconds: number | null; per_mode_and_severity: { source: string; mode: string; severity: number; runs: number; rows: number; accuracy_including_unknown: number; unknown_rate: number }[] }
export interface ModelReport<T> { provenance: string; profile?: string; report: T }
export interface ModelMetrics { models: State['models']; datasets?: Partial<Record<'anomaly' | 'source', { training_rows: number; training_runs: number; calibration_rows?: number; calibration_runs?: number }>>; evaluation: { status: 'idle' | 'running' | 'complete' | 'failed'; profile?: string; error?: string }; reports: { anomaly?: ModelReport<AnomalyReport>; source?: ModelReport<SourceReport> }; artifact_sha256: Record<string, string>; saved_report_errors: Record<string, string> }
export interface LiveData { state: State; points: TelemetryPoint[]; events: SystemEvent[]; incidents: IncidentList; sustainability: Sustainability; scenario: Scenario }

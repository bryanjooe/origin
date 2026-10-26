import type {
  HealthResponse, IncidentDetail, IncidentGraph, IncidentSummary, ModelMetrics,
  SimulationActionResponse, SustainabilityResponse, SystemState, TelemetryPoint,
  TopologyResponse, EventRecord, EvidenceItem, PredictionCandidate, TelemetryBatch,
  SecurityAttribution, SecurityMetrics,
} from '../types/domain'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
type JsonRecord = Record<string, unknown>

export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) { super(message); this.name = 'ApiError'; this.status = status }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers: { Accept: 'application/json', ...init?.headers } })
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : 'Could not reach the API.', 0)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string }; detail?: string } | null
    throw new ApiError(payload?.error?.message ?? payload?.detail ?? `Request failed (${response.status}).`, response.status)
  }
  return response.json() as Promise<T>
}

async function data<T>(path: string, init?: RequestInit): Promise<T> {
  const envelope = await request<{ data: T }>(path, init)
  return envelope.data
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return data<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
}

function record(value: unknown): JsonRecord { return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {} }
function number(value: unknown): number | undefined { return typeof value === 'number' && Number.isFinite(value) ? value : undefined }
function text(value: unknown): string | undefined { return typeof value === 'string' ? value : undefined }

export interface ScenarioPayload { scenario: string; seed?: number; speed?: number; severity?: number; start_tick?: number }
export interface FaultPayload { scenario: string; severity: number; start_tick: number; seed: number }

const faultModes: Record<string, { kind: string; mode: string }> = {
  sensor: { kind: 'sensor', mode: 'bias' }, communication: { kind: 'communication', mode: 'delay' },
  controller: { kind: 'controller', mode: 'wrong_dispatch' }, firmware: { kind: 'firmware', mode: 'discharge_limit' },
  inverter: { kind: 'inverter', mode: 'derate' }, actuator: { kind: 'inverter', mode: 'derate' },
}
function scenarioBody(payload: ScenarioPayload) {
  const mode = faultModes[payload.scenario]
  const start = Math.max(0, Math.floor(payload.start_tick ?? 30))
  return {
    seed: payload.seed ?? 42,
    config: {},
    fault: mode ? { ...mode, severity: payload.severity ?? 0.7, start_tick: start, duration_ticks: Math.max(1, Math.min(120, 10000 - start)) } : null,
  }
}

function mapTelemetry(item: unknown): TelemetryPoint {
  const wrapper = record(item)
  const telemetry = record(wrapper.telemetry ?? item)
  const anomaly = record(wrapper.anomaly)
  const source = record(wrapper.source)
  return {
    ...telemetry,
    tick: number(telemetry.tick), timestamp: text(telemetry.timestamp),
    solar_generation_kw: number(telemetry.actual_solar_kw), actual_solar_kw: number(telemetry.actual_solar_kw),
    demand_kw: number(telemetry.demand_kw), delivered_kw: number(telemetry.delivered_kw),
    battery_soc_pct: number(telemetry.battery_soc_pct), anomaly_score: number(anomaly.anomaly_score),
    ml_status: text(anomaly.ml_status), residual_status: text(anomaly.rule_status), combined_status: text(anomaly.combined_status),
    predicted_source: text(source.predicted_source), source_confidence: number(source.confidence),
  } as TelemetryPoint
}

function mapIncident(item: unknown): IncidentSummary {
  const raw = record(item), diagnosis = record(raw.diagnosis), created = text(raw.created_at)
  return {
    id: String(raw.id ?? ''), status: text(raw.status), severity: text(raw.severity),
    source: text(diagnosis.source) ?? 'unknown', predicted_source: text(diagnosis.source) === 'unknown' ? null : text(diagnosis.source) ?? null,
    confidence: number(diagnosis.confidence), anomaly_score: number(raw.peak_anomaly_score),
    timestamp: created, started_at: created, title: `${text(diagnosis.source) ?? 'Unknown'} source hypothesis`,
  }
}

function mapIncidentDetail(item: unknown): IncidentDetail {
  const raw = record(item), diagnosis = record(raw.diagnosis), explanation = record(raw.explanation)
  const base = mapIncident(raw)
  const candidates = Array.isArray(diagnosis.candidates) ? diagnosis.candidates.map((candidate): PredictionCandidate => {
    const value = record(candidate)
    return { source: text(value.label) ?? text(value.source), confidence: number(value.confidence) }
  }) : []
  const evidenceRaw = Array.isArray(raw.evidence) ? raw.evidence : []
  const evidence: EvidenceItem[] = evidenceRaw.map((item, index) => {
    const value = record(item)
    return { id: text(value.id) ?? index, type: text(value.kind), source: text(value.signal), description: text(value.description), value: value.value,
      timestamp: number(value.elapsed_seconds) === undefined ? undefined : `T+${value.elapsed_seconds}s` }
  })
  const deviations = Array.isArray(explanation.deviations) ? explanation.deviations.map((item) => record(item)) : []
  const describedEvidence: EvidenceItem[] = deviations.map((item, index) => ({ id: text(item.evidence_id) ?? `deviation-${index}`, type: 'Observed evidence', description: text(item.text) }))
  const trigger = record(raw.trigger_detection)
  const residualChecks = Array.isArray(trigger.residual_checks) ? trigger.residual_checks.map((item, index) => {
    const value = record(item)
    return { id: `residual-${index}`, type: 'Rule-based residual check', source: text(value.signal), description: `${text(value.signal) ?? 'Residual'}: ${String(value.value ?? '—')} ${text(value.unit) ?? ''} (threshold ${String(value.threshold ?? '—')})`, value: value.value }
  }) : []
  const timeline = Array.isArray(raw.timeline) ? raw.timeline.map((item) => {
    const event = record(item)
    return { ...event, event: text(event.event), simulation_time: number(event.elapsed_seconds), timestamp: number(event.tick) === undefined ? undefined : `Tick ${event.tick}` }
  }) : []
  const graph = record(raw.graph)
  return { ...base, summary: text(record(explanation).likely_source), candidates,
    evidence: describedEvidence.length ? describedEvidence : evidence, residual_checks: residualChecks,
    timeline, diagnostic_checks: Array.isArray(explanation.diagnostic_checks) ? explanation.diagnostic_checks.filter((item): item is string => typeof item === 'string') : [],
    affected_components: Array.isArray(graph.potentially_affected_nodes) ? graph.potentially_affected_nodes.filter((value): value is string => typeof value === 'string') : [],
    security_attribution: raw.security_attribution as SecurityAttribution | undefined,
  }
}

function mapModelMetrics(rawValue: unknown): ModelMetrics {
  const raw = record(rawValue), models = record(raw.models), reports = record(raw.reports)
  const sourceReport = record(record(reports.source).report)
  const detectorReport = record(record(reports.anomaly).report)
  const anomalyPerformance = record(detectorReport.performance)
  const detector = record(anomalyPerformance.ml)
  const sourceClass = record(sourceReport.per_class)
  const confusion = record(sourceReport.confusion_matrix)
  const labels = Array.isArray(confusion.labels) ? confusion.labels.filter((value): value is string => typeof value === 'string') : []
  const counts = Array.isArray(confusion.counts) ? confusion.counts.map((row) => Array.isArray(row) ? row.map(number).map((value) => value ?? 0) : []) : []
  const summary = record(detectorReport.performance)
  const combined = record(summary.combined)
  const rows = Array.isArray(detectorReport.by_mode_and_severity) ? detectorReport.by_mode_and_severity : []
  const severityRows = Array.isArray(detectorReport.by_mode_and_severity) ? detectorReport.by_mode_and_severity : []
  const trainingScenarios = record(raw.training_scenarios)
  const modelAvailable = ['anomaly', 'source'].some((name) => record(models[name]).available === true)
  const perClass = Object.entries(sourceClass).map(([label, value]) => {
    const metric = record(value)
    return { label, precision: number(metric.precision), recall: number(metric.recall), f1: number(metric['f1-score']), support: number(metric.support) }
  })
  return {
    trained: modelAvailable,
    model_status: modelAvailable ? 'available' : 'unavailable',
    dataset_size: number(sourceReport.rows),
    test_scenario_count: number(sourceReport.run_count),
    accuracy: number(sourceReport.accuracy_including_unknown),
    per_class: perClass,
    confusion_matrix: labels.length ? { labels, values: counts } : undefined,
    anomaly_detector: Object.keys(detector).length ? {
      precision: number(detector.precision), recall: number(detector.recall), f1: number(detector.f1),
      false_positive_rate: number(detector.false_positive_rate), detection_delay_seconds: number(detector.mean_detection_delay_seconds),
    } : undefined,
    train_scenario_count: number(trainingScenarios.source),
    by_severity: severityRows.length ? [...new Set(severityRows.map((row) => record(row).severity))].map((severity) => {
      const matching = severityRows.map(record).filter((item) => item.severity === severity)
      const recalls = matching.map((item) => number(item.combined_active_tick_recall)).filter((value): value is number => value !== undefined)
      return { severity: String(severity), recall: recalls.length ? recalls.reduce((sum, value) => sum + value, 0) / recalls.length : undefined }
    }) : rows.map((row) => {
      const item = record(row)
      return { severity: String(item.severity ?? 'unknown'), accuracy: number(item.accuracy_including_unknown) }
    }),
    evaluation_status: text(record(raw.evaluation).status),
    false_positive_rate: number(combined.false_positive_rate),
  }
}

export const api = {
  getHealth: async (): Promise<HealthResponse> => {
    const raw = record(await data<unknown>('/api/health'))
    const models = record(raw.models), available = Object.values(models).some((model) => record(model).available === true)
    return { status: text(raw.status), backend: { status: text(raw.status) }, model: { status: available ? 'available' : 'unavailable', trained: available } }
  },
  getSystemState: async (): Promise<SystemState> => {
    const [rawValue, sustainabilityValue, incidentValue, topologyValue] = await Promise.all([
      data<unknown>('/api/system/state'), data<unknown>('/api/metrics/sustainability'), data<unknown>('/api/incidents?status=open&limit=1'), data<TopologyResponse>('/api/system/topology'),
    ])
    const raw = record(rawValue), telemetry = record(raw.telemetry), sustainability = record(sustainabilityValue)
    const operated = record(record(sustainability.comparison).operated)
    const fraction = number(operated.renewable_delivery_fraction_of_generated)
    const anomaly = record(raw.anomaly), source = record(raw.source)
    const incidentListing = record(incidentValue)
    return {
      status: raw.running === true ? 'running' : 'paused', simulation_status: raw.running === true ? 'running' : 'paused',
      simulation_time_seconds: number(raw.simulated_seconds), sim_time_seconds: number(raw.simulated_seconds), next_tick: number(raw.next_tick),
      anomaly_status: text(anomaly.combined_status) ?? 'unknown', anomaly: { status: text(anomaly.combined_status), score: number(anomaly.anomaly_score), source: text(source.predicted_source) },
      model_status: Object.values(record(raw.models)).some((model) => record(model).available === true) ? 'available' : 'unavailable',
      backend_status: text(raw.runtime_error) ?? 'ok',
      metrics: {
        solar_generation_kw: number(telemetry.actual_solar_kw), battery_soc_pct: number(telemetry.battery_soc_pct),
        demand_kw: number(telemetry.demand_kw), energy_delivered_kwh: number(operated.delivered_kwh),
        renewable_utilization_pct: fraction === undefined ? undefined : fraction * 100,
        unmet_demand_kwh: number(operated.unmet_demand_kwh), active_incidents: number(incidentListing.total),
      },
      components: topologyValue.nodes.map((node) => ({ id: node.id, name: node.label ?? node.id, status: 'unknown' })),
    }
  },
  getTopology: async (): Promise<TopologyResponse> => data<TopologyResponse>('/api/system/topology'),
  startSimulation: async (payload: ScenarioPayload): Promise<SimulationActionResponse> => {
    await post('/api/simulation/scenario', scenarioBody(payload))
    const raw = record(await post('/api/simulation/start', { speed: payload.speed ?? 2 }))
    return { ...raw, simulation_status: 'running' }
  },
  pauseSimulation: async (): Promise<SimulationActionResponse> => { const raw = record(await post('/api/simulation/pause')); return { ...raw, simulation_status: 'paused' } },
  resumeSimulation: async (): Promise<SimulationActionResponse> => { const raw = record(await post('/api/simulation/resume')); return { ...raw, simulation_status: 'running' } },
  resetSimulation: async (seed?: number): Promise<SimulationActionResponse> => { const raw = record(await post('/api/simulation/reset', seed === undefined ? undefined : { seed })); return { ...raw, simulation_status: 'paused' } },
  setScenario: async (payload: ScenarioPayload): Promise<SimulationActionResponse> => { const raw = record(await post('/api/simulation/scenario', scenarioBody(payload))); return { ...raw, simulation_status: 'paused' } },
  injectFault: async (payload: FaultPayload): Promise<SimulationActionResponse> => {
    const mode = faultModes[payload.scenario]
    if (!mode) throw new ApiError('Choose a fault scenario before injecting a fault.', 422)
    const start = Math.max(0, Math.floor(payload.start_tick))
    const raw = record(await post('/api/simulation/inject-fault', { ...mode, severity: payload.severity, start_tick: start, duration_ticks: Math.max(1, Math.min(120, 10000 - start)) }))
    return { ...raw, message: 'Fault scheduled as simulated ground truth; it is not a model prediction.' }
  },
  setSpeed: async (speed: number): Promise<SimulationActionResponse> => record(await post('/api/simulation/speed', { speed })),
  applyCorrection: async (_incidentId: string | number): Promise<SimulationActionResponse> => { await post('/api/simulation/correct'); return { message: 'Simulated correction applied.' } },
  getTelemetry: async (afterTick = -1, limit = 360): Promise<TelemetryBatch> => {
    const raw = record(await data<unknown>(`/api/telemetry?after_tick=${afterTick}&limit=${limit}`))
    const items = Array.isArray(raw.items) ? raw.items.map(mapTelemetry) : []
    return { run_id: text(raw.run_id) ?? 'unknown', items, next_after_tick: number(raw.next_after_tick) ?? afterTick }
  },
  getEvents: async (limit = 12): Promise<EventRecord[]> => {
    const raw = record(await data<unknown>(`/api/events?limit=${limit}`))
    return Array.isArray(raw.items) ? raw.items.map((item) => { const event = record(item); return { ...event, timestamp: text(event.created_at), simulation_time: number(event.tick), event: text(event.event) } }) : []
  },
  getIncidents: async (): Promise<IncidentSummary[]> => {
    const raw = record(await data<unknown>('/api/incidents?limit=100'))
    return Array.isArray(raw.items) ? raw.items.map(mapIncident) : []
  },
  getIncident: async (id: string | number): Promise<IncidentDetail> => mapIncidentDetail(await data<unknown>(`/api/incidents/${encodeURIComponent(String(id))}`)),
  getIncidentGraph: async (id: string | number): Promise<IncidentGraph> => {
    const graph = await data<IncidentGraph>(`/api/incidents/${encodeURIComponent(String(id))}/graph`)
    return { ...graph, nodes: graph.nodes.map((node) => {
      const history = node.telemetry as unknown
      return { ...node, telemetry: Array.isArray(history) ? record(history.at(-1)) : record(history) }
    }) }
  },
  getSustainability: async (): Promise<SustainabilityResponse> => {
    const raw = record(await data<unknown>('/api/metrics/sustainability'))
    const comparison = record(raw.comparison), normal = record(comparison.baseline), faulty = record(comparison.faulty_uncorrected), operated = record(comparison.operated)
    const fraction = number(operated.demand_served_fraction)
    const chargeEfficiency = number(operated.observed_charge_efficiency), dischargeEfficiency = number(operated.observed_discharge_efficiency)
    const efficiency = chargeEfficiency === undefined || dischargeEfficiency === undefined ? undefined : chargeEfficiency * dischargeEfficiency
    return {
      generated_kwh: number(operated.solar_generated_kwh), delivered_kwh: number(operated.delivered_kwh), curtailed_kwh: number(operated.solar_curtailed_kwh),
      demand_served_pct: fraction === undefined ? undefined : fraction * 100, unmet_demand_kwh: number(operated.unmet_demand_kwh),
      battery_efficiency_pct: efficiency === undefined ? undefined : efficiency * 100,
      estimated_loss_kwh: number(raw.estimated_fault_delivery_loss_kwh),
      comparison: {
        normal: normalizeLedger(normal), faulty: normalizeLedger(faulty), after_correction: normalizeLedger(operated),
      },
      assumptions: Array.isArray(raw.assumptions) ? raw.assumptions.filter((item): item is string => typeof item === 'string') : [],
    }
  },
  getModelMetrics: async (): Promise<ModelMetrics> => mapModelMetrics(await data<unknown>('/api/model/metrics')),
  getSecurityMetrics: async (): Promise<SecurityMetrics> => data<SecurityMetrics>('/api/security/metrics'),
  evaluateModel: async (): Promise<ModelMetrics> => {
    const job = await post<unknown>('/api/model/evaluate', { profile: 'quick' })
    const result = mapModelMetrics(await data<unknown>('/api/model/metrics'))
    return { ...result, evaluation_status: text(record(job).status) ?? 'running' }
  },
  exportReport: async (format: 'csv' | 'json'): Promise<Blob> => {
    const response = await fetch(`${API_BASE}/api/reports/export?dataset=incidents&format=${format}`, { headers: { Accept: format === 'csv' ? 'text/csv' : 'application/json' } })
    if (!response.ok) throw new ApiError(`Export failed (${response.status}).`, response.status)
    return response.blob()
  },
}

function normalizeLedger(value: JsonRecord): Record<string, number | null> {
  return {
    generated_kwh: number(value.solar_generated_kwh) ?? null,
    delivered_kwh: number(value.delivered_kwh) ?? null,
    unmet_demand_kwh: number(value.unmet_demand_kwh) ?? null,
    curtailed_kwh: number(value.solar_curtailed_kwh) ?? null,
    demand_served_pct: number(value.demand_served_fraction) === undefined ? null : number(value.demand_served_fraction)! * 100,
  }
}

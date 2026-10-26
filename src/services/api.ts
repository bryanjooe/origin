import type {
  HealthResponse,
  IncidentDetail,
  IncidentGraph,
  IncidentSummary,
  ModelMetrics,
  SimulationActionResponse,
  SustainabilityResponse,
  SystemState,
  TelemetryPoint,
  TopologyResponse,
  EventRecord,
} from '../types/domain'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...init?.headers },
    })
  } catch (error) {
    throw new ApiError(error instanceof Error ? error.message : 'Could not reach the API.', 0)
  }
  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? ''
    if (contentType.includes('application/json')) {
      const payload: unknown = await response.json().catch(() => null)
      if (payload && typeof payload === 'object') {
        const record = payload as { detail?: unknown; message?: unknown; error?: unknown }
        const detail = record.detail ?? record.message ?? record.error
        if (typeof detail === 'string' && detail.trim()) throw new ApiError(detail, response.status)
      }
    }
    throw new ApiError(`Request failed (${response.status}).`, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export interface ScenarioPayload {
  scenario: string
  seed?: number
  speed?: number
}

export interface FaultPayload {
  scenario: string
  severity: number
  start_tick: number
  seed: number
}

export const api = {
  getHealth: () => request<HealthResponse>('/api/health'),
  getSystemState: () => request<SystemState>('/api/system/state'),
  getTopology: () => request<TopologyResponse>('/api/system/topology'),
  startSimulation: (payload: ScenarioPayload) => post<SimulationActionResponse>('/api/simulation/start', payload),
  pauseSimulation: () => post<SimulationActionResponse>('/api/simulation/pause'),
  resumeSimulation: () => post<SimulationActionResponse>('/api/simulation/resume'),
  resetSimulation: () => post<SimulationActionResponse>('/api/simulation/reset'),
  setScenario: (payload: ScenarioPayload) => post<SimulationActionResponse>('/api/simulation/scenario', payload),
  injectFault: (payload: FaultPayload) => post<SimulationActionResponse>('/api/simulation/inject-fault', payload),
  setSpeed: (speed: number) => post<SimulationActionResponse>('/api/simulation/speed', { speed }),
  applyCorrection: (incidentId: string | number) => post<SimulationActionResponse>('/api/simulation/correct', { incident_id: incidentId }),
  getTelemetry: (limit = 240) => request<TelemetryPoint[]>(`/api/telemetry?limit=${limit}`),
  getEvents: (limit = 12) => request<EventRecord[]>(`/api/events?limit=${limit}`),
  getIncidents: () => request<IncidentSummary[]>('/api/incidents'),
  getIncident: (id: string | number) => request<IncidentDetail>(`/api/incidents/${encodeURIComponent(String(id))}`),
  getIncidentGraph: (id: string | number) => request<IncidentGraph>(`/api/incidents/${encodeURIComponent(String(id))}/graph`),
  getSustainability: () => request<SustainabilityResponse>('/api/metrics/sustainability'),
  getModelMetrics: () => request<ModelMetrics>('/api/model/metrics'),
  evaluateModel: () => post<ModelMetrics>('/api/model/evaluate'),
  exportReport: async (format: 'csv' | 'json'): Promise<Blob> => {
    const response = await fetch(`${API_BASE}/api/reports/export?format=${format}`, { headers: { Accept: format === 'csv' ? 'text/csv' : 'application/json' } })
    if (!response.ok) throw new ApiError(`Export failed (${response.status}).`, response.status)
    return response.blob()
  },
}

export function telemetrySocketUrl(): string {
  const base = API_BASE ? new URL(API_BASE, window.location.origin) : new URL(window.location.origin)
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:'
  base.pathname = `${base.pathname.replace(/\/$/, '')}/ws/telemetry`.replace(/^\/\/ws/, '/ws')
  base.search = ''
  return base.toString()
}

export const API_CONTRACT_NOTE = 'Unspecified action routes use POST /api/simulation/speed and POST /api/simulation/correct; see README for the assumptions.'

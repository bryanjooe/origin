import { expect, it, vi } from 'vitest'
import { api } from './api'

it('uses backend component assessments instead of hardcoded unknown or source predictions', async () => {
  const payloads: Record<string, unknown> = {
    '/api/system/state': { running: true, simulated_seconds: 3660,
      telemetry: { measured_solar_kw: 12, controller_command_kw: 0 },
      anomaly: { residual_checks: [{ signal: 'solar_measurement_residual', value: 7, threshold: 5 }] },
      source: { predicted_source: 'controller' } },
    '/api/metrics/sustainability': {}, '/api/incidents?status=open&limit=1': { total: 0 },
    '/api/system/topology': { nodes: [{ id: 'solar_sensor' }, { id: 'controller' }, { id: 'battery' }], edges: [] },
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify({ data: payloads[url] }))))
  const state = await api.getSystemState()
  expect(state.simulation_time_seconds).toBe(3660)
  expect(state.components).toEqual([
    { id: 'solar_sensor', name: 'solar_sensor', status: 'observed_anomaly', severity: 'warning' },
    { id: 'controller', name: 'controller', status: 'unflagged', severity: 'normal' },
    { id: 'battery', name: 'battery', status: 'no_telemetry', severity: 'unknown' },
  ])
})

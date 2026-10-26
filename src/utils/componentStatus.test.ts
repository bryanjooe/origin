import { expect, it } from 'vitest'
import { componentStatus } from './componentStatus'

it('keeps missing telemetry and unavailable detection explicit', () => {
  expect(componentStatus('solar', {}).status).toBe('no_telemetry')
  expect(componentStatus('solar', { actual_solar_kw: 0 }).status).toBe('telemetry_available')
  expect(componentStatus('solar', { actual_solar_kw: 0 }, { residual_checks: [] }).status).toBe('unflagged')
})

it('flags only observed nodes and preserves missing-packet observations', () => {
  const detection = { residual_checks: [{ signal: 'stale_telemetry' }] }
  expect(componentStatus('communication', { controller_inputs: null }, detection).status).toBe('observed_anomaly')
  expect(componentStatus('controller', { controller_command_kw: 0 }, detection).status).toBe('unflagged')
  expect(componentStatus('demand_sensor', { controller_inputs: null }, detection).status).toBe('no_telemetry')
})

it('ignores injected labels and source predictions', () => {
  expect(componentStatus('controller', { controller_command_kw: 0, attack_target: 'controller' }, { residual_checks: [], predicted_source: 'controller' }).status).toBe('unflagged')
})

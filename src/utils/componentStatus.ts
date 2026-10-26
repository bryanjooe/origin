// Current observable fields and residual-to-node mapping from the existing backend
// topology and explainability/evidence.py. No injected labels or source predictions.
const fields: Record<string, string> = {
  irradiance: 'irradiance', solar: 'actual_solar_kw', solar_sensor: 'measured_solar_kw',
  battery: 'battery_soc_pct', battery_sensor: 'measured_soc_pct', demand: 'demand_kw',
  demand_sensor: 'controller_inputs', communication: 'controller_inputs', controller: 'controller_command_kw',
  firmware: 'config_integrity_ok', inverter: 'inverter_actual_kw', delivered: 'delivered_kw',
}
const signalNodes: Record<string, string[]> = {
  solar_measurement_residual: ['solar_sensor'], soc_step_residual: ['battery_sensor'],
  soc_energy_estimate_residual: ['battery_sensor'], inverter_output_residual: ['inverter'],
  controller_policy_residual: ['controller'], stale_telemetry: ['communication'],
  configuration_integrity: ['firmware'], packet_local_solar_disagreement: ['communication', 'solar_sensor'],
  unmet_demand: ['delivered'],
}

export function componentStatus(id: string, telemetry: Record<string, unknown>, detection?: Record<string, unknown>) {
  const checks = Array.isArray(detection?.residual_checks) ? detection.residual_checks : []
  const flagged = checks.some((check: { signal?: string }) => signalNodes[check.signal ?? '']?.includes(id))
  if (flagged) return { status: 'observed_anomaly', severity: 'warning' }
  let value = telemetry[fields[id] ?? '']
  if (id === 'demand_sensor') value = value && typeof value === 'object' ? (value as Record<string, unknown>).demand_kw : undefined
  if (value === undefined || value === null || (typeof value === 'number' && !Number.isFinite(value))) return { status: 'no_telemetry', severity: 'unknown' }
  if (!detection) return { status: 'telemetry_available', severity: 'unknown' }
  return { status: 'unflagged', severity: 'normal' }
}

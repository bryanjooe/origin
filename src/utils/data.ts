import type { MetricValues, TelemetryPoint } from '../types/domain'

export function formatNumber(value: number | null | undefined, fractionDigits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString(undefined, { maximumFractionDigits: fractionDigits })
}

export function readMetric(metrics: MetricValues | undefined, ...keys: string[]): number | undefined {
  if (!metrics) return undefined
  for (const key of keys) {
    const value = metrics[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
  }
  return undefined
}

export function normalizeTelemetry(rows: TelemetryPoint[]): TelemetryPoint[] {
  return rows.slice(-360).map((row, index) => ({
    ...row,
    tick: row.tick ?? index,
    solar_generation_kw: row.solar_generation_kw ?? row.actual_solar_kw,
    delivered_kw: row.delivered_kw ?? row.energy_delivered_kw,
    simulation_time: row.simulation_time ?? row.timestamp ?? row.time ?? row.tick ?? index,
  }))
}

export function displayTime(value?: string | number): string {
  if (typeof value === 'string') return value || 'Unknown time'
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unknown time'
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

export function percent(value: number | null | undefined): number | undefined {
  if (value === null || value === undefined || !Number.isFinite(value)) return undefined
  return value <= 1 ? value * 100 : value
}

import type { Severity } from '../types/domain'

export function getSeverity(value?: string): Severity {
  const normalized = value?.toLowerCase()
  if (normalized === 'normal' || normalized === 'healthy' || normalized === 'ok') return 'normal'
  if (normalized === 'warning' || normalized === 'degraded') return 'warning'
  if (normalized === 'critical' || normalized === 'error' || normalized === 'failed') return 'critical'
  return 'unknown'
}

export function simulationLabel(value?: string): string {
  return value?.replaceAll('_', ' ').toUpperCase() ?? 'UNKNOWN'
}

// Elapsed simulation time in hours:minutes, shared by both dashboard clocks.
export function simulationClock(value?: string | number, seconds?: number): string {
  if (typeof value === 'string' && /^\d+:\d{2}$/.test(value)) return value
  const total = typeof value === 'number' ? value : seconds
  if (typeof total !== 'number' || !Number.isFinite(total) || total < 0) return '—'
  const minutes = Math.floor(total / 60)
  return `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}`
}

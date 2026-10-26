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

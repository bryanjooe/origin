import type { Source } from '../types'
export const number = (value: number | null | undefined, digits = 2) => value == null || !Number.isFinite(value) ? '—' : new Intl.NumberFormat('en', { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value)
export const percent = (value: number | null | undefined, digits = 1) => value == null ? '—' : `${number(value * 100, digits)}%`
export const human = (value: string) => value.replaceAll('_', ' ').replace(/^./, char => char.toUpperCase())
export const sourceLabel = (source?: Source | string | null) => ({ normal: 'Normal', sensor: 'Sensor', communication: 'Communication', controller: 'Controller', firmware: 'Firmware / config', inverter: 'Actuator / inverter', unknown: 'Insufficient evidence' }[source ?? 'unknown'] ?? human(source ?? 'unknown'))
export function simTime(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
}
export const wallTime = (value: string) => new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

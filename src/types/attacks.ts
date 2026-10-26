// Mirrors backend Attack / AttackRequest. Scheduling remains server-authoritative.
export const attackTargets = {
  solar_sensor: 'Solar sensor', battery_sensor: 'Battery sensor', demand_sensor: 'Demand sensor',
  communication: 'Communication', controller: 'Controller', firmware: 'Firmware', inverter: 'Inverter',
} as const
export type AttackTarget = keyof typeof attackTargets
export const attackOptions = {
  sensor_spoof: { label: 'Sensor spoofing', targets: ['solar_sensor', 'battery_sensor', 'demand_sensor'] },
  replay: { label: 'Replay attack', targets: ['communication'] },
  communication_degradation: { label: 'Communication degradation', targets: ['communication'] },
  message_tampering: { label: 'Message tampering', targets: ['communication', 'controller', 'inverter'] },
  controller_compromise: { label: 'Controller compromise', targets: ['controller'] },
  firmware_tampering: { label: 'Firmware tampering', targets: ['firmware'] },
  actuator_abuse: { label: 'Actuator abuse', targets: ['inverter'] },
  multi_stage: { label: 'Multi-stage attack', targets: Object.keys(attackTargets) as AttackTarget[] },
} satisfies Record<string, { label: string; targets: AttackTarget[] }>
export type AttackType = keyof typeof attackOptions
export type StealthLevel = 'naive' | 'moderate' | 'stealthy'
export interface AttackPayload {
  attack_type: AttackType
  target_component: AttackTarget
  severity: number
  duration_ticks: number
  stealth_level: StealthLevel
  start_tick?: number
}
export interface AttackScheduleResponse {
  scheduled: AttackPayload & { start_tick: number }
  label: string
}
// Default ServerSettings limit; custom limits are checked by the API.
export const ATTACK_TICK_LIMIT = 10000

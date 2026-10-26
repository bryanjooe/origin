import { useEffect, useRef, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { Button, Card } from './ui'
import { ATTACK_TICK_LIMIT, attackOptions, attackTargets } from '../types/attacks'
import type { AttackPayload, AttackScheduleResponse, AttackTarget, AttackType, StealthLevel } from '../types/attacks'

export function CyberattackInjection({ nextTick, runId, disabled, loading, onSchedule }: {
  nextTick?: number
  runId?: string
  disabled: boolean
  loading: boolean
  onSchedule: (payload: AttackPayload) => Promise<AttackScheduleResponse | undefined>
}) {
  const [attackType, setAttackType] = useState<AttackType>('sensor_spoof')
  const [target, setTarget] = useState<AttackTarget>('solar_sensor')
  const [severity, setSeverity] = useState('0.7')
  const [duration, setDuration] = useState('30')
  const [stealth, setStealth] = useState<StealthLevel>('moderate')
  const [schedule, setSchedule] = useState('next')
  const [start, setStart] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<AttackScheduleResponse | null>(null)
  const submitting = useRef(false)
  const targets: readonly AttackTarget[] = attackOptions[attackType].targets
  useEffect(() => { setSuccess(null); setError(null) }, [runId])

  async function submit() {
    if (disabled || loading || submitting.current) return
    setSuccess(null)
    setError(null)
    const strength = Number(severity), ticks = Number(duration)
    const tick = schedule === 'next' ? nextTick : Number(start)
    if (!targets.includes(target)) { setError('Choose a compatible target component.'); return }
    if (!severity.trim() || !Number.isFinite(strength) || strength <= 0 || strength > 1) {
      setError('Attack severity must be greater than 0 and at most 1.'); return
    }
    if (!Number.isInteger(ticks) || ticks < 1 || ticks > ATTACK_TICK_LIMIT) {
      setError('Attack duration must be an integer from 1 to 10000 ticks.'); return
    }
    if (nextTick === undefined || tick === undefined || !Number.isInteger(tick) ||
      (schedule === 'future' && (!start.trim() || tick <= nextTick)) || tick < 0 || tick + ticks > ATTACK_TICK_LIMIT) {
      setError('Start tick and duration must finish by tick 10000. A future start tick must be later than the current simulation tick.'); return
    }
    submitting.current = true
    try {
      const result = await onSchedule({ attack_type: attackType, target_component: target,
        severity: strength, duration_ticks: ticks, stealth_level: stealth,
        ...(schedule === 'future' ? { start_tick: tick } : {}) })
      if (result) setSuccess(result)
    } finally { submitting.current = false }
  }

  return <Card title="Cyberattack Injection" eyebrow="CONTROL / SECURITY">
    <form noValidate onSubmit={(event) => { event.preventDefault(); void submit() }} onChange={() => { setSuccess(null); setError(null) }}>
      <div className="control-grid">
        <label className="field-label">ATTACK TYPE
          <select aria-label="Attack type" value={attackType} disabled={disabled} onChange={(event) => {
            const next = event.target.value as AttackType
            setAttackType(next)
            const compatible: readonly AttackTarget[] = attackOptions[next].targets
            if (!compatible.includes(target)) setTarget(compatible[0]!)
          }}>{Object.entries(attackOptions).map(([value, option]) => <option key={value} value={value}>{option.label}</option>)}</select>
        </label>
        <label className="field-label">TARGET COMPONENT
          <select aria-label="Target component" value={target} disabled={disabled} onChange={(event) => setTarget(event.target.value as AttackTarget)}>
            {targets.map((value) => <option key={value} value={value}>{attackTargets[value]}</option>)}
          </select>
        </label>
        <label className="field-label">ATTACK SEVERITY
          <input aria-label="Attack severity" type="number" min="0" max="1" step="any" value={severity} disabled={disabled} onChange={(event) => setSeverity(event.target.value)} />
        </label>
        <label className="field-label">DURATION (TICKS)
          <input aria-label="Attack duration" type="number" min="1" max={ATTACK_TICK_LIMIT} step="1" value={duration} disabled={disabled} onChange={(event) => setDuration(event.target.value)} />
        </label>
        <label className="field-label">STEALTH LEVEL
          <select aria-label="Stealth level" value={stealth} disabled={disabled} onChange={(event) => setStealth(event.target.value as StealthLevel)}>
            <option value="naive">Naive</option><option value="moderate">Moderate</option><option value="stealthy">Stealthy</option>
          </select>
        </label>
        <label className="field-label">ATTACK START
          <select aria-label="Attack start" value={schedule} disabled={disabled} onChange={(event) => setSchedule(event.target.value)}>
            <option value="next">Next simulation tick</option><option value="future">Future tick</option>
          </select>
        </label>
        {schedule === 'future' && <label className="field-label">ATTACK START TICK
          <input aria-label="Attack start tick" type="number" min={(nextTick ?? 0) + 1} max={ATTACK_TICK_LIMIT - 1} step="1" value={start} disabled={disabled} onChange={(event) => setStart(event.target.value)} />
        </label>}
      </div>
      <div className="control-actions"><Button type="submit" variant="secondary" icon={<ShieldAlert size={14} />} disabled={disabled} loading={loading}>Inject Cyberattack</Button></div>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {success && <p role="status">Cyberattack scheduled successfully at tick {success.scheduled.start_tick} for {success.scheduled.duration_ticks} ticks. {success.label}</p>}
      <p className="control-footnote">Simulation only. Scheduling does not confirm execution or anomaly detection. Severity must be greater than 0. The server checks timing and overlapping attacks.</p>
    </form>
  </Card>
}

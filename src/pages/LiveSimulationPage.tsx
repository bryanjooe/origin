import { useRef, useState } from 'react'
import { Activity, Pause, Play, RotateCcw, ShieldAlert, SlidersHorizontal } from 'lucide-react'
import { api } from '../services/api'
import { useApiResource } from '../hooks/useApiResource'
import { useLiveTelemetry } from '../hooks/useLiveTelemetry'
import type { ComponentStatus } from '../types/domain'
import { normalizeTelemetry } from '../utils/data'
import { TimeSeriesChart } from '../components/charts/TimeSeriesChart'
import { Badge, Button, Card, EmptyState } from '../components/ui'
import { CyberattackInjection } from '../components/CyberattackInjection'
import { getSeverity, simulationLabel } from '../utils/status'

const scenarios = [
  { value: 'normal', label: 'Normal operation' },
  { value: 'sensor', label: 'Sensor' },
  { value: 'communication', label: 'Communication' },
  { value: 'controller', label: 'Controller' },
  { value: 'firmware', label: 'Firmware / config' },
  { value: 'actuator', label: 'Actuator / inverter' },
]

export function LiveSimulationPage() {
  const system = useApiResource('simulation-system', api.getSystemState, 3_000)
  const { points, stream, error: telemetryError } = useLiveTelemetry()
  const [scenario, setScenario] = useState('normal')
  const [severity, setSeverity] = useState(0.7)
  const [startTick, setStartTick] = useState('30')
  const [seed, setSeed] = useState('42')
  const [speed, setSpeed] = useState(1)
  const [pending, setPending] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionNotice, setActionNotice] = useState<string | null>(null)
  const actionLock = useRef(false)
  const status = (system.data?.simulation_status ?? system.data?.status ?? 'unknown').toLowerCase()
  const isRunning = status === 'running'
  const isPaused = status === 'paused'
  const canStart = status !== 'running' && status !== 'unknown'
  const validStartTick = /^\d+$/.test(startTick) && Number(startTick) <= 10_000
  const validSeed = /^\d+$/.test(seed) && Number(seed) <= 2_147_483_647
  const canInjectAtTick = validStartTick && Number(startTick) >= (system.data?.next_tick ?? 0)
  const components = system.data?.components ?? []
  const simulationSeconds = system.data?.simulation_time_seconds ?? system.data?.sim_time_seconds

  async function perform<T,>(name: string, task: () => Promise<T>): Promise<T | undefined> {
    if (actionLock.current || pending) return
    actionLock.current = true
    setPending(name)
    setActionError(null)
    setActionNotice(null)
    try {
      const result = await task()
      if (name === 'inject' && result && typeof result === 'object' && 'scheduled' in result) {
        const scheduled = result.scheduled as { start_tick?: number } | undefined
        if (typeof scheduled?.start_tick === 'number') setActionNotice(`Fault scheduled at tick ${scheduled.start_tick}.`)
      }
      system.reload()
      return result
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Simulation action failed.')
    } finally {
      actionLock.current = false
      setPending(null)
    }
  }

  const simulationScenario = scenario === 'actuator' ? 'inverter' : scenario
  const normalized = normalizeTelemetry(points)

  return (
    <>
      <div className="page-intro">
        <div><p className="eyebrow">MICROGRID / CONTROL ROOM</p><h1>Live simulation</h1><p className="intro-copy">Run and inspect a simulated microgrid scenario. Controls act on the simulation only.</p></div>
        <div className="intro-actions"><Badge severity={getSeverity(status)}>{simulationLabel(status)}</Badge></div>
      </div>

      {system.error && <EmptyState title="Simulation state unavailable" detail={system.error} kind="error" action={<Button variant="secondary" onClick={system.reload}>Retry</Button>} />}
      {actionError && <div className="inline-error" role="alert"><ShieldAlert size={15} />{actionError}</div>}
      {actionNotice && <div className="inline-notice" role="status">{actionNotice}</div>}

      <div className="simulation-layout">
        <Card title="Simulation controls" eyebrow="CONTROL / RUN" className="controls-card">
          <div className="control-grid">
            <label className="field-label">SCENARIO
              <select value={scenario} disabled={pending !== null || !system.data} onChange={(event) => setScenario(event.target.value)}>
                {scenarios.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label className="field-label">SIMULATION SPEED
              <select value={speed} disabled={pending !== null || !system.data} onChange={(event) => {
                const next = Number(event.target.value)
                setSpeed(next)
                void perform('speed', () => api.setSpeed(next))
              }}>
                <option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={5}>5×</option>
              </select>
            </label>
            <label className="field-label">FAULT SEVERITY <span>{severity.toFixed(2)}</span>
              <input aria-label="Fault severity" type="range" min="0.05" max="1" step="0.05" value={severity} disabled={scenario === 'normal' || pending !== null || !system.data} onChange={(event) => setSeverity(Number(event.target.value))} />
            </label>
            <label className="field-label">FAULT START TICK
              <input aria-label="Fault start tick" type="number" min="0" max="10000" step="1" value={startTick} disabled={scenario === 'normal' || pending !== null || !system.data} onChange={(event) => setStartTick(event.target.value)} />
            </label>
            <label className="field-label">RANDOM SEED <span>NEXT RUN</span>
              <input aria-label="Random seed" type="number" min="0" max="2147483647" step="1" value={seed} disabled={pending !== null || !system.data} onChange={(event) => setSeed(event.target.value)} />
            </label>
          </div>
          <p className="muted-small">Choose a fault type and start tick to schedule it in the running simulation. The seed is used when you start or reset a run; changing it does not alter a run already in progress.{isRunning && scenario !== 'normal' && !canInjectAtTick ? ` Choose a tick at or after ${system.data?.next_tick ?? 0} to inject this fault.` : ''}</p>
          <div className="control-actions">
            <Button variant="primary" icon={<Play size={14} />} loading={pending === 'start'} disabled={!canStart || pending !== null || !!system.error || !system.data || !validStartTick || !validSeed} onClick={() => void perform('start', () => api.startSimulation({ scenario: simulationScenario, seed: Number(seed), speed, severity, start_tick: Number(startTick) }))}>Start</Button>
            <Button icon={<Pause size={14} />} loading={pending === 'pause'} disabled={!isRunning || pending !== null || !system.data} onClick={() => void perform('pause', api.pauseSimulation)}>Pause</Button>
            <Button icon={<Play size={14} />} loading={pending === 'resume'} disabled={!isPaused || pending !== null || !system.data} onClick={() => void perform('resume', api.resumeSimulation)}>Resume</Button>
            <Button variant="quiet" icon={<RotateCcw size={14} />} loading={pending === 'reset'} disabled={pending !== null || !system.data || isRunning || !validSeed} onClick={() => void perform('reset', () => api.resetSimulation(Number(seed)))}>Reset</Button>
            <Button variant="secondary" icon={<SlidersHorizontal size={14} />} loading={pending === 'inject'} disabled={scenario === 'normal' || pending !== null || !isRunning || !canInjectAtTick} onClick={() => void perform('inject', () => api.injectFault({ scenario: simulationScenario, severity, seed: Number(seed), start_tick: Number(startTick) }))}>Inject fault</Button>
          </div>
          <p className="control-footnote"><ShieldAlert size={13} />All actions are simulation-only. A selected fault scenario is simulated ground truth, separate from model predictions.</p>
        </Card>

        <Card title="Simulation clock" eyebrow="TIME / STATE" className="clock-card">
          <div className="large-clock">{typeof system.data?.simulation_time === 'string' ? system.data.simulation_time : typeof simulationSeconds === 'number' ? formatElapsed(simulationSeconds) : '—'}</div>
          <div className="clock-meta"><span><i className="live-dot" />{isRunning ? 'ADVANCING' : isPaused ? 'PAUSED' : 'NOT RUNNING'}</span><span><Activity size={12} />{stream.toUpperCase()}</span></div>
          {!system.data && !system.loading && <EmptyState title="Clock unavailable" detail={system.error ?? 'No simulation state returned by the API.'} kind={system.error ? 'error' : 'unknown'} />}
        </Card>
      </div>

      <CyberattackInjection nextTick={system.data?.next_tick} runId={system.data?.run_id}
        disabled={pending !== null || !system.data || !!system.error || status === 'unknown'} loading={pending === 'attack'}
        onSchedule={(payload) => perform('attack', () => api.injectAttack(payload))} />

      <div className="two-column-grid simulation-lower">
        <Card title="Live power telemetry" eyebrow="TELEMETRY / STREAM" action={<span className="micro-label">LAST {normalized.length} SAMPLES</span>}>
          {telemetryError && normalized.length === 0 ? <EmptyState title="Telemetry unavailable" detail={telemetryError} kind="error" /> : <TimeSeriesChart data={normalized} unit="kW" series={[{ key: 'solar_generation_kw', label: 'Solar', color: 'var(--chart-solar)' }, { key: 'demand_kw', label: 'Demand', color: 'var(--chart-demand)' }, { key: 'delivered_kw', label: 'Delivered', color: 'var(--chart-delivered)' }]} />}
        </Card>
        <Card title="Component telemetry" eyebrow="TELEMETRY / OBSERVED FIELDS">
          {system.loading && !system.data ? <EmptyState title="Loading component telemetry" kind="loading" /> : components.length ? <div className="component-list">{components.map((component: ComponentStatus) => <div className="component-row" key={component.id}><div><span className="component-name">{component.name ?? component.component ?? component.id}</span>{component.telemetry && Object.keys(component.telemetry).length > 0 && <small className="component-reading">{formatComponentTelemetry(component.telemetry)}</small>}</div><Badge severity="unknown">{component.status === 'reporting' ? 'DATA RECEIVED' : 'NO DATA'}</Badge></div>)}</div> : <EmptyState title="Component telemetry unavailable" detail="The system state response did not include component telemetry." kind="unknown" />}
        </Card>
      </div>
    </>
  )
}

function formatElapsed(seconds: number): string {
  const totalMinutes = Math.floor(Math.max(0, seconds) / 60)
  const hours = Math.floor(totalMinutes / 60).toString().padStart(2, '0')
  const minutes = (totalMinutes % 60).toString().padStart(2, '0')
  return `${hours}:${minutes}`
}

function formatComponentTelemetry(telemetry: Record<string, unknown>): string {
  return Object.entries(telemetry).slice(0, 2).map(([key, value]) => {
    const label = key.replaceAll('_', ' ')
    const formatted = typeof value === 'number' ? `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : typeof value === 'boolean' ? (value ? 'yes' : 'no') : typeof value === 'string' ? value : 'available'
    return `${label}: ${formatted}`
  }).join(' · ')
}

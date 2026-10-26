import { useState } from 'react'
import { FastForward, Pause, Play, RotateCcw, ShieldCheck, Wrench, Zap } from 'lucide-react'
import type { PageProps } from '../App'
import type { FaultSpec } from '../types'
import { useAction } from '../hooks/useData'
import { ActionFeedback, Badge, PageHeading, Panel } from '../components/ui'
import { BatteryChart, PowerChart } from '../components/Charts'
import { human, number, simTime } from '../utils/format'

export const faultModes: Record<FaultSpec['kind'], string[]> = {
  sensor: ['bias', 'drift', 'stuck', 'noise', 'soc_bias'], communication: ['delay', 'drop', 'stale', 'corrupt'],
  controller: ['wrong_dispatch'], firmware: ['discharge_limit', 'reserve_threshold'], inverter: ['derate', 'shutdown', 'efficiency', 'delay'],
}
export default function Simulation({ data, refresh, offline }: PageProps) {
  const { state, scenario } = data
  const { act, busy, error, message } = useAction(refresh)
  const [kind, setKind] = useState<FaultSpec['kind']>('inverter')
  const [mode, setMode] = useState('derate')
  const [severity, setSeverity] = useState(0.8)
  const [duration, setDuration] = useState(60)
  const [scheduled, setScheduled] = useState(false)
  const [startTick, setStartTick] = useState(30)
  const [seed, setSeed] = useState(scenario.metadata.seed)
  const [speed, setSpeed] = useState(state.speed_ticks_per_second)
  const [stepCount, setStepCount] = useState(20)
  const disabled = busy || offline
  const fault = { kind, mode, severity, duration_ticks: duration, ...(scheduled ? { start_tick: startTick } : {}) }
  return <>
    <PageHeading eyebrow="THE MICROGRID LAB" title="Live simulation" description="Run a healthy grid, introduce a controlled fault, and watch the system respond." action={<span className="label-pill"><ShieldCheck size={15} />Software-only environment</span>} />
    <ActionFeedback error={error} message={message} />
    <Panel className="control-panel"><div className="simulation-clock"><div className="eyebrow">SIMULATED ELAPSED TIME</div><strong>{simTime(state.simulated_seconds)}</strong><span>Next tick {state.next_tick} · {state.config.tick_seconds}s per tick</span></div><div className="control-actions">
      <button className={`button ${state.running ? '' : 'primary'}`} disabled={disabled} onClick={() => act(state.running ? '/simulation/pause' : '/simulation/start', state.running ? undefined : { speed }, state.running ? 'Simulation paused' : 'Simulation running')}>{state.running ? <Pause size={16} /> : <Play size={16} />}{state.running ? 'Pause simulation' : state.next_tick ? 'Resume simulation' : 'Start simulation'}</button>
      <button className="button" disabled={disabled || state.running} onClick={() => act('/simulation/reset', undefined, 'Run reset; previous history is retained')}><RotateCcw size={15} />Reset run</button>
      <div className="step-control"><input aria-label="Ticks to advance" type="number" min={1} max={300} value={stepCount} onChange={event => setStepCount(Number(event.target.value))} /><button className="button" disabled={disabled || state.running || stepCount < 1 || stepCount > 300 || !Number.isInteger(stepCount)} onClick={() => act('/simulation/step', { ticks: stepCount }, `Advanced ${stepCount} ticks`)}><FastForward size={16} />Advance ticks</button></div>
    </div><label className="speed-control">Target speed<select aria-label="Simulation speed" value={speed} disabled={disabled} onChange={event => { const value = Number(event.target.value); setSpeed(value); void act('/simulation/speed', { speed: value }, `Target speed set to ${value} ticks/second`) }}>{[0.5, 1, 2, 5, 10, 20, 30].map(value => <option key={value} value={value}>{value} ticks / sec</option>)}</select></label></Panel>
    <div className="simulation-layout"><div className="space-y-5"><Panel title="Power telemetry" eyebrow="CURRENT RUN" action={<Badge value={state.anomaly?.combined_status ?? (state.models.anomaly.available ? 'pending' : 'unavailable')} />}><PowerChart points={data.points} detailed /><div className="chart-footnote">Sensor-reported values are separate from actual simulated output.</div></Panel>
      <Panel title="Battery state of charge" action={<span className="muted text-xs">Physical vs sensor-reported SOC</span>}><BatteryChart points={data.points} /></Panel>
      <Panel title="Controller & delivery"><div className="reading-grid">{[
        ['Battery command', state.telemetry?.controller_command_kw, 'kW'], ['Inverter request', state.telemetry?.inverter_requested_kw, 'kW'],
        ['Inverter output', state.telemetry?.inverter_actual_kw, 'kW'], ['Message age', state.telemetry?.message_age_seconds, 's'],
      ].map(([label, value, unit]) => <div key={String(label)}><span>{label}</span><strong>{number(value as number | null)} <small>{unit}</small></strong></div>)}</div><p className="fine-print">Battery command: positive means discharge; negative means charge.</p></Panel>
    </div><div className="space-y-5"><Panel title="Introduce a disruption" eyebrow="FAULT INJECTION"><form onSubmit={event => { event.preventDefault(); void act('/simulation/inject-fault', fault, 'Fault scheduled in the software simulation') }} className="form-stack">
      <label>System layer<select aria-label="Fault type" value={kind} onChange={event => { const value = event.target.value as FaultSpec['kind']; setKind(value); setMode(faultModes[value][0]) }}>{Object.keys(faultModes).map(value => <option key={value} value={value}>{human(value)}</option>)}</select></label>
      <label>Fault behavior<select aria-label="Fault mode" value={mode} onChange={event => setMode(event.target.value)}>{faultModes[kind].map(value => <option key={value} value={value}>{human(value)}</option>)}</select></label>
      <label className="range-label"><span>Severity <strong>{Math.round(severity * 100)}%</strong></span><input aria-label="Fault severity" type="range" min={0.05} max={1} step={0.05} value={severity} onChange={event => setSeverity(Number(event.target.value))} /><small>Scenario intensity; not model confidence.</small></label>
      <label>Duration in ticks<input aria-label="Fault duration" type="number" min={1} max={10000} required value={duration} onChange={event => setDuration(Number(event.target.value))} /></label>
      <label>Start time<select aria-label="Fault start time" value={scheduled ? 'scheduled' : 'now'} onChange={event => { const value = event.target.value === 'scheduled'; setScheduled(value); if (value) setStartTick(Math.max(30, state.next_tick + 10)) }}><option value="now">Immediately at the next tick</option><option value="scheduled">At a chosen simulation tick</option></select></label>
      {scheduled && <label>Start tick<input aria-label="Fault start tick" type="number" min={0} max={10000} value={startTick} required onChange={event => setStartTick(Number(event.target.value))} /></label>}
      <button className="button amber full" type="submit" disabled={disabled}><Zap size={15} />Inject simulated fault</button>
    </form><p className="fine-print">One active fault at a time. Timing and overlap are validated in both comparison runs.</p></Panel>
    <Panel title="Restore normal components"><p className="muted">Restore simulated components while preserving stored energy and elapsed time.</p><button className="button full" disabled={disabled} onClick={() => act('/simulation/correct', undefined, 'Simulated components restored. Resume or advance ticks to observe recovery.')}><Wrench size={15} />Apply simulated correction</button></Panel></div></div>
    <Panel title="Repeatable scenarios" eyebrow="START FRESH" action={<Badge value={state.running ? 'warning' : 'normal'}>{state.running ? 'Pause to configure' : 'Ready to configure'}</Badge>}><div className="scenario-controls"><label>Random seed<input aria-label="Random seed" type="number" min={0} max={2147483647} value={seed} onChange={event => setSeed(Number(event.target.value))} /></label><button className="button" disabled={disabled || state.running} onClick={() => act('/simulation/scenario', { seed, config: state.config }, 'Created a healthy, repeatable scenario')}><ShieldCheck size={15} />New healthy scenario</button><button className="button" disabled={disabled || state.running} onClick={() => act('/simulation/scenario', { seed, config: state.config, fault }, 'Created a new scenario with the configured fault')}>New scenario with this fault</button></div><p className="fine-print">Starts at tick 0 and archives the current run. A scheduled tick is interpreted within the new run.</p></Panel>
    <details className="truth-panel"><summary>Simulated scenario ground truth <span>Separate from model predictions</span></summary><p className="muted">Injection records from the simulator. They are not inference inputs or proof of model correctness.</p>{scenario.metadata.ground_truth.faults.length ? <div className="table-scroll"><table><thead><tr><th>Source</th><th>Behavior</th><th>Severity</th><th>Start</th><th>Duration</th><th>Cancelled</th></tr></thead><tbody>{scenario.metadata.ground_truth.faults.map((item, i) => <tr key={i}><td>{human(item.kind)}</td><td>{human(item.mode)}</td><td>{number(item.severity * 100, 0)}%</td><td>Tick {item.start_tick}</td><td>{item.duration_ticks} ticks</td><td>{item.cancelled_at_tick == null ? '—' : `Tick ${item.cancelled_at_tick}`}</td></tr>)}</tbody></table></div> : <p>No fault has been injected into this run.</p>}</details>
  </>
}

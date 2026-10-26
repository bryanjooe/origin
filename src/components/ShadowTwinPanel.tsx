import { useEffect, useMemo, useRef, useState } from 'react'
import type { SystemState, TelemetryPoint } from '../types/domain'
import type { ShadowComparison, ShadowHypothesis } from '../types/shadowtwin'
import { api } from '../services/api'
import { formatNumber } from '../utils/data'
import { Badge, Button, Card, EmptyState } from './ui'
import { TimeSeriesChart } from './charts/TimeSeriesChart'
import './ShadowTwinPanel.css'

export const shadowChoices: (ShadowHypothesis & {name: string})[] = [
  {hypothesis_id:'solar_fault', name:'Solar sensor malfunction', component:'solar_sensor', mechanism:'Possible solar sensor malfunction', intervention:'use_redundant_solar'},
  {hypothesis_id:'solar_manipulation', name:'Solar measurement manipulation', component:'solar_sensor', mechanism:'Possible solar measurement manipulation', intervention:'use_redundant_solar'},
  {hypothesis_id:'controller_fault', name:'Controller malfunction', component:'controller', mechanism:'Possible controller malfunction', intervention:'restore_controller_policy'},
  {hypothesis_id:'controller_manipulation', name:'Controller command manipulation', component:'controller', mechanism:'Possible controller command manipulation', intervention:'restore_controller_policy'},
  {hypothesis_id:'communication_buffer', name:'Stale communication buffers', component:'communication', mechanism:'Possible stale communication buffers', intervention:'flush_communication'},
  {hypothesis_id:'communication_manipulation', name:'Communication manipulation', component:'communication', mechanism:'Possible communication manipulation', intervention:'flush_communication'},
]
const metrics = {
  inverter_actual_kw: {name:'Actual inverter output', unit:'kW'},
  inverter_requested_kw: {name:'Requested inverter output', unit:'kW'},
  delivered_kw: {name:'Delivered power', unit:'kW'},
  measured_solar_kw: {name:'Solar measurement', unit:'kW'},
  battery_soc_pct: {name:'Battery state of charge', unit:'%'},
} as const
const shown = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? formatNumber(value, 6) : 'Unavailable'
const nameOf = (id: string) => shadowChoices.find(choice => choice.hypothesis_id === id)?.name ?? id

export function ShadowTwinPanel({incidentId, system}: {incidentId?: string | number; system?: SystemState | null}) {
  const [selected, setSelected] = useState<string[]>([])
  const [duration, setDuration] = useState('20')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ShadowComparison | null>(null)
  const [inspected, setInspected] = useState('')
  const [metric, setMetric] = useState<keyof typeof metrics>('inverter_actual_kw')
  const busy = useRef(false), generation = useRef(0), mounted = useRef(true)
  const scope = `${system?.run_id ?? ''}|${incidentId ?? 'manual'}`
  const currentScope = useRef(scope)
  currentScope.current = scope
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++ } }, [])
  useEffect(() => { generation.current++; setResult(null); setError(null) }, [scope])

  async function submit() {
    if (busy.current) return
    setError(null)
    const ticks = Number(duration)
    if (selected.length < 2) { setError('Select at least two different hypotheses.'); return }
    if (!duration.trim() || !Number.isInteger(ticks) || ticks < 1 || ticks > 1000 || ticks * selected.length * 2 > 480) {
      setError('Choose a positive whole duration within the 480 control/experimental branch-tick budget.'); return
    }
    if (!system?.run_id) { setError('Current simulation state is unavailable.'); return }
    if (system.next_tick !== undefined && system.next_tick + ticks > 10000) {
      setError('The experiment must finish within the simulation tick limit.'); return
    }
    const token = ++generation.current, requestScope = currentScope.current, runId = system.run_id
    busy.current = true; setPending(true); setResult(null)
    try {
      const response = await api.compareShadowTwin({hypotheses: selected.map(id => {
        const {name: _name, ...hypothesis} = shadowChoices.find(choice => choice.hypothesis_id === id)!
        return hypothesis
      }), duration_ticks: ticks, expected_run_id: runId,
      ...(incidentId === undefined ? {} : {incident_id: String(incidentId)})})
      if (!mounted.current || token !== generation.current || requestScope !== currentScope.current) return
      if (!response || response.run_id !== runId || !Number.isInteger(response.snapshot_tick) ||
          !Array.isArray(response.hypotheses) || !response.hypotheses.length || typeof response.status !== 'string' ||
          !Array.isArray(response.inconclusive_reasons) || !Array.isArray(response.limitations) || !Array.isArray(response.tied_or_tradeoff_groups) ||
          response.hypotheses.some(item => !item || typeof item.hypothesis_id !== 'string' || typeof item.explanation !== 'string' ||
            !Array.isArray(item.warnings) || !item.physical_observations ||
            (item.experiment !== null && (!Array.isArray(item.experiment?.control_telemetry) || !Array.isArray(item.experiment?.experimental_telemetry))))) {
        throw new Error('The backend returned missing or incompatible ShadowTwin comparison data.')
      }
      setResult(response); setInspected(response.hypotheses[0]!.hypothesis_id)
    } catch (caught) {
      if (mounted.current && token === generation.current && requestScope === currentScope.current)
        setError(caught instanceof Error ? caught.message : 'ShadowTwin analysis failed.')
    } finally {
      busy.current = false
      if (mounted.current) setPending(false)
    }
  }
  const focused = result?.hypotheses.find(item => item.hypothesis_id === inspected)
  const chart = useMemo<TelemetryPoint[]>(() => {
    const experiment = focused?.experiment
    if (!experiment) return []
    const other = new Map(experiment.experimental_telemetry.map(row => [row.tick, row]))
    return experiment.control_telemetry.flatMap(row => {
      const paired = other.get(row.tick)
      return paired ? [{tick:row.tick, timestamp:`Tick ${row.tick}`, control:row[metric], experimental:paired[metric]}] : []
    })
  }, [focused, metric])
  function changeSelection(id: string) {
    setResult(null); setError(null)
    setSelected(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id])
  }
  return <Card title="ShadowTwin — Virtual Investigation" eyebrow="ISOLATED / PROSPECTIVE EXPERIMENTS" className="shadowtwin-panel">
    <p className="uncertainty-note">ShadowTwin tests possible interventions from a captured simulation state. These experiments do not independently prove the historical origin of an attack.</p>
    <p className="muted-small">{incidentId === undefined ? 'Manual prospective experiment; no incident evidence is invented.' : `Incident reference: ${incidentId}.`} Analysis always captures the current run, not the incident’s original start time.</p>
    <fieldset disabled={pending} className="shadowtwin-options"><legend>Select hypotheses to compare</legend>
      <div className="shadowtwin-choices">{shadowChoices.map(choice => <label key={choice.hypothesis_id} className="shadowtwin-choice">
        <input type="checkbox" checked={selected.includes(choice.hypothesis_id)} onChange={() => changeSelection(choice.hypothesis_id)} />
        <span>{choice.name}<small>{choice.component} · {choice.intervention.replaceAll('_', ' ')}</small></span>
      </label>)}</div>
    </fieldset>
    <p className="muted-small">Select 2–6 hypotheses. Different explanations can use the same intervention and remain indistinguishable. Communication flushing is temporary and does not remove an ongoing manipulation.</p>
    <div className="shadowtwin-actions">
      <label className="field-label">Experiment duration (ticks)<input aria-label="ShadowTwin duration" type="number" min="1" max={Math.min(1000, Math.floor(480 / Math.max(2, selected.length * 2)))} value={duration} disabled={pending} onChange={event => {setDuration(event.target.value); setResult(null); setError(null)}} /></label>
      <Button variant="primary" loading={pending} disabled={pending || !system?.run_id} onClick={() => void submit()}>Run ShadowTwin Analysis</Button>
    </div>
    {pending && <p role="status">Running isolated virtual experiments; existing investigation data remains available.</p>}
    {!system?.run_id && <p className="muted-small">Current simulation state is unavailable. Analysis will be available when the backend reconnects.</p>}
    {error && <p role="alert" className="inline-error">{error}</p>}
    {result && <div className="shadowtwin-results">
      <Badge severity={result.status === 'Inconclusive' ? 'warning' : 'normal'}>{result.status}</Badge>
      {result.status === 'Inconclusive' && <p>Inconclusive — Available evidence does not distinguish these hypotheses.</p>}
      <p className="muted-small">Captured run <code>{result.run_id}</code> · Snapshot tick {result.snapshot_tick} · Comparison window {result.start_tick}–{result.end_tick - 1}. Historical source: {result.historical_source}.</p>
      {result.historical_incident && <p role="status">Historical incident reference only. Its old evidence was not applied to the current run; no historical reconstruction was performed.</p>}
      {(result.run_changed || result.run_id !== system?.run_id) && <p role="alert" className="inline-error">The simulation run changed. These completed results belong only to captured run {result.run_id}.</p>}
      {result.inconclusive_reasons.map(reason => <p className="muted-small" key={reason}>{reason}</p>)}
      {result.tied_or_tradeoff_groups.map(group => <p key={group.join('|')}>Equivalent or trade-off group: {group.map(nameOf).join(' / ')}. No arbitrary tie-break was applied.</p>)}
      {result.hypotheses.map(item => <article className="shadowtwin-result" key={item.hypothesis_id}>
        <h3>{nameOf(item.hypothesis_id)}</h3>
        <p className="muted-small">{item.suspected_component} · {item.intervention} · Experiment: {item.experiment_status}</p>
        <dl className="detail-dl">
          <div><dt>Source evidence</dt><dd>{item.evidence_assessment}</dd></div>
          <div><dt>Intervention outcome</dt><dd>{item.intervention_outcome}</dd></div>
          <div><dt>Evidence / intervention front</dt><dd>{item.ranking_position ?? 'Unranked'} / {item.intervention_rank ?? 'Unranked'}</dd></div>
          <div><dt>Delivered-energy difference</dt><dd>{item.delivered_energy_difference_kwh != null && item.delivered_energy_difference_kwh > 0 ? '+' : ''}{shown(item.delivered_energy_difference_kwh)}{item.delivered_energy_difference_kwh == null ? '' : ' kWh'}</dd></div>
        </dl>
        <p className="shadowtwin-explanation">{item.explanation}</p>
        {item.exclusion_reason && <p className="muted-small">{item.exclusion_reason}</p>}
        <details><summary>Measured residuals and experiment limitations</summary>
          {Object.entries(item.physical_observations).map(([signal, observation]) => <p key={signal}>{signal}: above-limit mean {shown(observation.control_mean_excess)} → {shown(observation.experimental_mean_excess)} {observation.unit}</p>)}
          {[...item.warnings, ...(item.experiment?.limitations ?? [])].map((text, index) => <p className="muted-small" key={index}>{text}</p>)}
        </details>
      </article>)}
      <div className="control-grid">
        <label className="field-label">Inspect hypothesis<select aria-label="ShadowTwin result hypothesis" value={inspected} onChange={event => setInspected(event.target.value)}>{result.hypotheses.map(item => <option key={item.hypothesis_id} value={item.hypothesis_id}>{nameOf(item.hypothesis_id)}</option>)}</select></label>
        <label className="field-label">Measurement<select aria-label="ShadowTwin measurement" value={metric} onChange={event => setMetric(event.target.value as keyof typeof metrics)}>{Object.entries(metrics).map(([key, value]) => <option key={key} value={key}>{value.name} ({value.unit})</option>)}</select></label>
      </div>
      <h3>Control vs ShadowTwin</h3><p className="muted-small">Matching simulation ticks · {metrics[metric].name} ({metrics[metric].unit})</p>
      {chart.length ? <TimeSeriesChart data={chart} unit={metrics[metric].unit} series={[{key:'control',label:'Control',color:'#a9622f'},{key:'experimental',label:'ShadowTwin',color:'#17684f'}]} /> : <EmptyState title="No matching comparison telemetry" detail="This experiment did not return paired observations; no measurements are invented." kind="unknown" />}
      <details><summary>Comparison limitations and independent model context</summary>
        {result.limitations.map(text => <p className="muted-small" key={text}>{text}</p>)}
        {Object.entries(result.independent_model_evidence ?? {}).map(([name, model]) => <p className="muted-small" key={name}>{name}: {model.prediction ?? 'Unavailable'}{model.nature ? ` · ${model.nature}` : ''}. Model predictions remain separate from experimental effects.</p>)}
      </details>
    </div>}
  </Card>
}

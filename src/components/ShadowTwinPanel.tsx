import { useEffect, useMemo, useRef, useState } from 'react'
import type { SystemState, TelemetryPoint } from '../types/domain'
import type { ShadowComparison, ShadowHypothesis, ShadowIncidentContext } from '../types/shadowtwin'
import { api } from '../services/api'
import { formatNumber } from '../utils/data'
import { Badge, Button, Card, EmptyState } from './ui'
import { TimeSeriesChart } from './charts/TimeSeriesChart'
import { Sun, Cpu, Network, ShieldCheck, ArrowRight } from 'lucide-react'
import { interventionNames, signalNames, outcomeLabel, shadowConclusion } from './shadowTwinPresentation'
import './ShadowTwinPanel.css'

export const shadowChoices: (ShadowHypothesis & {name: string})[] = [
  {hypothesis_id:'solar_fault', name:'Solar sensor malfunction', component:'solar_sensor', mechanism:'Possible solar sensor malfunction', intervention:'use_redundant_solar'},
  {hypothesis_id:'solar_manipulation', name:'Solar measurement manipulation', component:'solar_sensor', mechanism:'Possible solar measurement manipulation', intervention:'use_redundant_solar'},
  {hypothesis_id:'controller_fault', name:'Controller malfunction', component:'controller', mechanism:'Possible controller malfunction', intervention:'restore_controller_policy'},
  {hypothesis_id:'controller_manipulation', name:'Controller command manipulation', component:'controller', mechanism:'Possible controller command manipulation', intervention:'restore_controller_policy'},
  {hypothesis_id:'communication_buffer', name:'Stale communication buffers', component:'communication', mechanism:'Possible stale communication buffers', intervention:'flush_communication'},
  {hypothesis_id:'communication_manipulation', name:'Communication manipulation', component:'communication', mechanism:'Possible communication manipulation', intervention:'flush_communication'},
]
export const shadowCategories = [
  {name:'Solar Measurement', component:'solar_sensor', description:'Test whether using the redundant solar measurement changes system behavior.', Icon:Sun},
  {name:'Controller Behavior', component:'controller', description:'Test whether restoring normal controller commands improves operation.', Icon:Cpu},
  {name:'Communication', component:'communication', description:'Test whether clearing buffered communication data changes system behavior.', Icon:Network},
] as const
const metrics = {
  inverter_actual_kw: {name:'Actual inverter output', unit:'kW'},
  inverter_requested_kw: {name:'Requested inverter output', unit:'kW'},
  delivered_kw: {name:'Delivered power', unit:'kW'},
  measured_solar_kw: {name:'Solar measurement', unit:'kW'},
  battery_soc_pct: {name:'Battery state of charge', unit:'%'},
} as const
const shown = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? formatNumber(value, 6) : 'Unavailable'
const nameOf = (id: string) => shadowChoices.find(choice => choice.hypothesis_id === id)?.name ?? id

export function ShadowTwinPanel({incidentId, system, incident}: {incidentId?: string | number; system?: SystemState | null; incident?: ShadowIncidentContext}) {
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
      setResult(response)
      const front = response.intervention_ranking?.find(group => group.position === 1)
      setInspected(front?.hypothesis_ids.length === 1 ? front.hypothesis_ids[0]! : response.hypotheses[0]!.hypothesis_id)
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
  function chooseCategory(component: string) {
    const ids = shadowChoices.filter(choice => choice.component === component).map(choice => choice.hypothesis_id)
    setResult(null); setError(null)
    setSelected(current => ids.every(id => current.includes(id)) ? current.filter(id => !ids.includes(id)) : [...new Set([...current, ...ids])])
  }
  const conclusion = result ? shadowConclusion(result) : null
  const snapshotTick = result?.snapshot_tick ?? system?.next_tick
  const differentRun = result?.historical_incident || (!!incident?.runId && !!system?.run_id && incident.runId !== system.run_id)
  const historical = differentRun
    || (incident?.endTick !== undefined && snapshotTick !== undefined && incident.endTick < snapshotTick)
  const anomaly = system?.anomaly_status ?? system?.anomaly?.status
  const observation = anomaly === 'normal' ? 'No current anomaly flag' : anomaly === 'warning' || anomaly === 'critical' ? 'Current anomaly flag detected' : 'Current anomaly assessment unavailable'
  return <Card title="ShadowTwin — Virtual Investigation" eyebrow="TEST POSSIBLE CAUSES SAFELY" className="shadowtwin-panel">
    <p className="st-intro">Test possible causes of an incident in a virtual copy of the energy system, without affecting the live simulation.</p>
    <section className="st-step" aria-labelledby="st-context-title">
      <h3 id="st-context-title"><span className="st-step-number">1</span>Select Investigation</h3>
      <div className="st-context-grid">
        <div><span>Selected incident</span><strong>{incident?.title ?? (incidentId === undefined ? 'Manual prospective experiment' : 'Selected incident')}</strong><small>{incident?.status ? `Recorded status: ${incident.status.replaceAll('_', ' ')}` : 'No incident status available'}</small></div>
        <div><span>Current simulation</span><strong>{system?.simulation_status ?? system?.status ?? 'Status unavailable'}</strong><small>Current tick: {system?.next_tick ?? 'Not available'}</small></div>
        <div><span>Observable condition</span><strong>{observation}</strong><small>A live anomaly flag does not guarantee a relevant abnormality in the experiment window.</small></div>
      </div>
      <div className={`st-context-note ${historical ? 'st-historical' : ''}`}>
        <strong>{historical ? 'Historical Incident — Current-State Test' : 'Current-State Test — No Historical Replay'}</strong>
        <p>ShadowTwin is testing the system’s current condition, not replaying the incident from its original start.</p>
        {differentRun && <p>The incident and snapshot belong to different simulation runs. Their tick numbers are not a single timeline.</p>}
        <div className="st-time-pair"><span>Incident observation period: <b>{incident?.startTick !== undefined ? `Ticks ${incident.startTick}–${incident.endTick ?? incident.startTick}` : 'Not available'}</b></span><span>{result ? 'Experiment snapshot' : 'Current tick (snapshot captured on run)'}: <b>{snapshotTick ?? 'Not available'}</b></span></div>
        {result?.historical_incident && <p>Historical incident reference only. Its old evidence was not applied to the current run; no historical reconstruction was performed.</p>}
      </div>
    </section>
    <section className="st-step" aria-labelledby="st-tests-title">
      <h3 id="st-tests-title"><span className="st-step-number">2</span>Choose What to Test</h3>
      <p>Select a category to test both supported explanations, or expand it to choose individually. Compare at least two hypotheses.</p>
      <fieldset disabled={pending} className="shadowtwin-options"><legend className="sr-only">Select hypotheses to compare</legend>
        <div className="st-categories">{shadowCategories.map(({name, component, description, Icon}) => {
          const choices = shadowChoices.filter(choice => choice.component === component)
          const count = choices.filter(choice => selected.includes(choice.hypothesis_id)).length
          return <article className={`st-category ${count ? 'st-category-selected' : ''}`} key={component}>
            <div className="st-category-heading"><Icon size={22} aria-hidden="true" /><h4>{name}</h4></div><p>{description}</p>
            <button type="button" className="button st-category-button" aria-label={`Test ${name}`} aria-pressed={count > 0} onClick={() => chooseCategory(component)}>{count ? `${count} explanation${count === 1 ? '' : 's'} selected` : 'Select test'}<ArrowRight size={14} aria-hidden="true" /></button>
            <details><summary>Choose explanations ({count}/2)</summary>
              {choices.map(choice => <label key={choice.hypothesis_id} className="shadowtwin-choice"><input type="checkbox" checked={selected.includes(choice.hypothesis_id)} onChange={() => changeSelection(choice.hypothesis_id)} /><span>{choice.name}</span></label>)}
              <p className="st-small">Both explanations use the same intervention. Equivalent results cannot distinguish malfunction from manipulation.</p>
            </details>
          </article>
        })}</div>
      </fieldset>
      <p className="st-small">Communication clearing is temporary; it does not remove ongoing manipulation. These experiments do not independently prove historical origin or malicious intent.</p>
    </section>
    <section className="st-step" aria-labelledby="st-run-title">
      <h3 id="st-run-title"><span className="st-step-number">3</span>Run Investigation</h3>
      <p className="st-selection-summary">{selected.length ? `${selected.length} hypotheses selected: ${selected.map(nameOf).join(' · ')}` : 'Choose what to test above. No hypotheses are selected yet.'}</p>
      <details className="st-advanced"><summary>Advanced Settings</summary>
        <label className="field-label">Experiment duration (ticks)<input aria-label="ShadowTwin duration" type="number" min="1" max={Math.min(1000, Math.floor(480 / Math.max(2, selected.length * 2)))} value={duration} disabled={pending} onChange={event => {setDuration(event.target.value); setResult(null); setError(null)}} /></label>
        <p className="st-small">Default: 20 ticks. Up to 480 total control/intervention branch ticks; the experiment must finish before tick 10000.</p>
      </details>
      <div className="shadowtwin-actions"><Button variant="primary" loading={pending} disabled={pending || !system?.run_id} onClick={() => void submit()}>Run ShadowTwin Analysis</Button><span><ShieldCheck size={16} aria-hidden="true" />Experiments run in isolated simulations. Your live system will not be modified.</span></div>
      {pending && <p role="status" className="st-loading">Running isolated virtual experiments and comparing their measured effects. Please wait; you can continue reviewing the incident above.</p>}
      {!system?.run_id && <p className="st-small">Current simulation state is unavailable. Analysis will be available when the backend reconnects.</p>}
      {error && <p role="alert" className="inline-error">{error}</p>}
    </section>
    {result && conclusion && <div className="shadowtwin-results" aria-live="polite">
      <section className={`st-conclusion st-conclusion-${conclusion.kind}`} aria-labelledby="st-conclusion-title">
        <span className="eyebrow">INVESTIGATION CONCLUSION</span><h3 id="st-conclusion-title">{conclusion.title}</h3><p>{conclusion.detail}</p>
        <Badge severity={conclusion.kind}>{result.status}</Badge>
        <p className="st-small">Intervention evidence is not proof of historical attack origin. These experiments do not independently prove malicious intent.</p>
        {result.inconclusive_reasons.length > 0 && <ul>{result.inconclusive_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>}
      </section>
      {(result.run_changed || result.run_id !== system?.run_id) && <p role="alert" className="inline-error">The simulation run changed. These completed results belong only to captured run {result.run_id}.</p>}
      <section className="st-comparison" aria-labelledby="st-comparison-title">
        <h3 id="st-comparison-title">What Changed in the Virtual Experiment?</h3>
        <div className="control-grid">
          <label className="field-label">Viewing intervention<select aria-label="ShadowTwin result hypothesis" value={inspected} onChange={event => setInspected(event.target.value)}>{result.hypotheses.map(item => <option key={item.hypothesis_id} value={item.hypothesis_id}>{nameOf(item.hypothesis_id)}</option>)}</select></label>
          <label className="field-label">Measurement<select aria-label="ShadowTwin measurement" value={metric} onChange={event => setMetric(event.target.value as keyof typeof metrics)}>{Object.entries(metrics).map(([key, value]) => <option key={key} value={key}>{value.name} ({value.unit})</option>)}</select></label>
        </div>
        {focused && <>
          <p className="st-viewing"><strong>{nameOf(focused.hypothesis_id)}</strong> · {interventionNames[focused.intervention] ?? focused.intervention} intervention · {outcomeLabel(focused.intervention_outcome)}</p>
          <div className="st-measurements">
            {Object.entries(focused.physical_observations).map(([signal, value]) => <div key={signal}><span>{signalNames[signal] ?? signal.replaceAll('_', ' ')}</span><strong>{shown(value.control_mean_excess)} <span aria-label="changed to">→</span> {shown(value.experimental_mean_excess)} <small>{value.unit}</small></strong><small>Mean excess above the existing rule limit · original → intervention</small></div>)}
            {!Object.keys(focused.physical_observations).length && <div><span>Relevant abnormality measurements</span><strong>Not available</strong></div>}
            <div><span>Delivered-energy difference</span><strong>{focused.delivered_energy_difference_kwh != null && focused.delivered_energy_difference_kwh > 0 ? '+' : ''}{shown(focused.delivered_energy_difference_kwh)}{focused.delivered_energy_difference_kwh == null ? '' : ' kWh'}</strong><small>Intervention minus original behavior; not historical energy savings.</small></div>
          </div>
        </>}
        <p className="st-small">Matching simulation ticks · {metrics[metric].name} ({metrics[metric].unit})</p>
        {chart.length ? <TimeSeriesChart data={chart} unit={metrics[metric].unit} series={[{key:'control',label:'Original simulated behavior',color:'#a9622f'},{key:'experimental',label:'ShadowTwin intervention',color:'#17684f'}]} /> : <EmptyState title="No matching comparison telemetry" detail="This experiment did not return paired observations; no measurements are invented." kind="unknown" />}
      </section>
      <section className="st-ranking" aria-labelledby="st-ranking-title"><h3 id="st-ranking-title">Compare Tested Explanations</h3>
        <p className="st-small">Backend rankings are preserved. Intervention effectiveness and source evidence are separate; ranks are not confidence percentages.</p>
        {result.tied_or_tradeoff_groups.map(group => <p className="st-tie" key={group.join('|')}>Equivalent or trade-off group: {group.map(nameOf).join(' / ')}. No arbitrary tie-break was applied.</p>)}
        {!result.intervention_ranking?.length && <p>No meaningful intervention ranking was returned.</p>}
        <div className="st-table-scroll"><table className="st-table"><thead><tr><th>Hypothesis</th><th>Intervention outcome</th><th>Relevant abnormality change</th><th>Source evidence</th><th>Result</th></tr></thead><tbody>{result.hypotheses.map(item => <tr key={item.hypothesis_id}>
          <th scope="row">{nameOf(item.hypothesis_id)}</th><td>{outcomeLabel(item.intervention_outcome)}</td>
          <td>{Object.entries(item.physical_observations).length ? Object.entries(item.physical_observations).map(([signal, value]) => <div key={signal}>{signalNames[signal] ?? signal.replaceAll('_',' ')}: {shown(value.control_mean_excess)} → {shown(value.experimental_mean_excess)} {value.unit}</div>) : 'Not available'}</td>
          <td>{item.evidence_assessment}</td><td>{item.experiment_status !== 'completed' ? item.experiment_status : item.intervention_rank == null ? 'Unranked' : `Intervention group ${item.intervention_rank}`}<small>Source: {item.ranking_position == null ? 'Unranked' : `evidence group ${item.ranking_position}`}</small></td>
        </tr>)}</tbody></table></div>
      </section>
      <details className="st-technical"><summary>View Technical Evidence</summary>
        <p>Captured run <code>{result.run_id}</code> · Snapshot tick {result.snapshot_tick} · Comparison window {result.start_tick}–{result.end_tick - 1}. Historical source: {result.historical_source}.</p>
        <p>Earlier incident observations and independent model context are historical supporting records, not measurements produced by this experiment.</p>
        <div className="st-technical-scroll">{result.hypotheses.map(item => <article className="shadowtwin-result" key={item.hypothesis_id}>
          <h4>{nameOf(item.hypothesis_id)}</h4><p>Experiment: {item.experiment_status} · {item.intervention} · {item.suspected_component}</p>
          <p>{item.explanation}</p>{item.exclusion_reason && <p>{item.exclusion_reason}</p>}
          {item.recorded_evidence_ids?.length ? <p>Earlier incident evidence IDs: {item.recorded_evidence_ids.join(', ')}</p> : <p>No earlier evidence IDs linked to this hypothesis.</p>}
          <pre>{JSON.stringify({physical_observations:item.physical_observations, experiment:item.experiment}, null, 2)}</pre>
          {[...new Set([...item.warnings, ...(item.experiment?.warnings ?? []), ...(item.experiment?.limitations ?? [])])].map((text,index) => <p key={index}>{text}</p>)}
        </article>)}
        {result.limitations.map(text => <p key={text}>{text}</p>)}
        {Object.entries(result.independent_model_evidence ?? {}).map(([name, model]) => <p key={name}>{name}: {model.prediction ?? 'Unavailable'}{model.nature ? ` · ${model.nature}` : ''}. Model predictions remain separate from experimental effects.</p>)}
        </div>
      </details>
    </div>}
  </Card>
}

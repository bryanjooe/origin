import { useEffect, useMemo, useRef, useState } from 'react'
import { Bot, Play, ShieldCheck } from 'lucide-react'
import { api } from '../services/api'
import { useApiResource } from '../hooks/useApiResource'
import type { SystemState, TelemetryPoint } from '../types/domain'
import type { AgentIncident, AgentReport, AgentStep } from '../types/investigationAgent'
import { Badge, Button, Card, EmptyState } from './ui'
import { TimeSeriesChart } from './charts/TimeSeriesChart'
import { formatNumber } from '../utils/data'
import { interventionNames, outcomeLabel, signalNames } from './shadowTwinPresentation'
import './AutonomousAgentPanel.css'

const stages: Record<string,string> = {capturing_snapshot:'Capturing a consistent snapshot',reviewing_evidence:'Reviewing incident evidence',selecting_experiment:'Selecting a diagnostic experiment',running_shadowtwin:'Running ShadowTwin',evaluating_results:'Evaluating measured results',checking_uncertainty:'Checking remaining uncertainty',decision_recorded:'Recording the next decision',generating_report:'Generating the investigation report',finished:'Finished',failed:'Failed',skipped:'Skipped'}
const label = (value?: string | null) => value?.replaceAll('_',' ') ?? 'Not available'
const shown = (value?: number | null) => value == null ? 'Not available' : formatNumber(value,6)

export function AutonomousAgentPanel({system,incidentId,incident}: {system?:SystemState|null;incidentId?:string|number;incident?:AgentIncident}) {
  const status = useApiResource('agent-status',api.getAgentStatus,2000)
  const [selected,setSelected]=useState<string|null>(null)
  const [followLatest,setFollowLatest]=useState(true)
  const [pending,setPending]=useState(false)
  const [error,setError]=useState<string|null>(null)
  const lock=useRef(false)
  const requested=useRef<string|null>(null)
  const currentRun=system?.run_id
  const currentRunRef=useRef(currentRun)
  currentRunRef.current=currentRun
  useEffect(()=>{requested.current=null;setSelected(null);setFollowLatest(true);setError(null)},[currentRun])
  useEffect(()=>{
    if (!followLatest || !currentRun || status.data?.current_run_id !== currentRun) return
    if (requested.current) {
      if (!status.data.recent.some(item=>item.id===requested.current)) return
      requested.current=null
    }
    const job=status.data.active?.run_id===currentRun ? status.data.active : status.data.latest
    if (job?.run_id===currentRun) setSelected(job.id)
  },[status.data,currentRun,followLatest])
  const detail=useApiResource(`agent-result-${selected ?? 'none'}`,()=>api.getAgentInvestigation(selected!),status.data?.active?.id===selected ? 1500 : undefined,selected!==null)
  const job=detail.data?.id===selected ? detail.data : null
  const report=job?.report
  const stale=!!job && (job.run_id!==currentRun || job.stale)
  const active=!!status.data?.active
  const automatic=status.data?.automatic_enabled
  async function act(task:()=>Promise<unknown>) {
    if(lock.current)return
    lock.current=true;setPending(true);setError(null)
    try {await task();status.reload()}
    catch(caught){setError(caught instanceof Error ? caught.message : 'Investigation request failed.')}
    finally{lock.current=false;setPending(false)}
  }
  const steps=report?.steps ?? job?.progress_steps ?? []
  const history=status.data?.recent ?? []
  const window=report?.initial_plan.context.incident_observation_window
  const historical=!!incident && (!!incident.runId && incident.runId!==currentRun || incident.endTick!==undefined && (job?.snapshot_tick ?? system?.next_tick ?? 0)>incident.endTick)
  return <Card title="Autonomous Investigation Agent" eyebrow="AGENT / ISOLATED EVIDENCE" className="agent-panel" action={<Bot size={20} aria-hidden="true" />}>
    <p className="agent-intro">Let the agent choose useful diagnostic tests, run isolated ShadowTwin experiments, and explain what the measurements support.</p>
    <div className="agent-controls">
      <div><strong>{typeof automatic==='boolean' && !status.error ? `Automatic Investigation ${automatic ? 'Enabled' : 'Disabled'}` : 'Automatic mode unavailable'}</strong><p>{typeof automatic!=='boolean' || status.error ? 'Automatic-mode state is unavailable. Reconnect to confirm whether new automatic investigations are enabled.' : automatic ? 'OriginX will automatically investigate qualifying new incidents using isolated ShadowTwin experiments.' : 'Automatic investigation is disabled. You can still start an investigation manually.'}</p></div>
      <button className="button" type="button" role="switch" aria-label="Automatic Investigation" aria-checked={automatic===true} disabled={pending || typeof automatic!=='boolean' || !!status.error} onClick={()=>void act(()=>api.setAgentAutoMode(!automatic))}>{automatic ? 'Turn automatic OFF' : 'Turn automatic ON'}</button>
      <Button variant="primary" icon={<Play size={14} />} loading={pending} disabled={pending || active || !currentRun || !!status.error} onClick={()=>void act(async()=>{const run=currentRun!;const started=await api.startAgentInvestigation(run,incidentId===undefined?undefined:String(incidentId));if(currentRunRef.current!==run)return;requested.current=started.id;setSelected(started.id);setFollowLatest(true)})}>Start AI Investigation</Button>
    </div>
    <div className="agent-status-line"><Badge severity={active?'warning':job?.status==='failed'?'critical':'unknown'} status={active?'running':'idle'}>{active?'Investigating':selected && detail.loading && !job?'Loading report':label(job?.status ?? 'idle')}</Badge><span>{active ? stages[status.data?.active?.stage ?? ''] ?? label(status.data?.active?.stage) : job?.reason ?? 'No active investigation'}</span>{status.data?.active?.incident_id && <small>Incident {status.data.active.incident_id}</small>}</div>
    <p className="agent-note"><ShieldCheck size={14} aria-hidden="true" />Virtual experiments cannot modify the live system. Disabling automatic mode prevents new jobs; current isolated work completes safely. Settings and recent reports reset when the backend restarts.</p>
    {(error || status.error || selected && detail.error) && <p role="alert" className="inline-error">{error ?? status.error ?? detail.error}</p>}
    {status.loading && !status.data && <EmptyState title="Loading agent status" kind="loading" />}
    {selected && detail.loading && !job && <EmptyState title="Loading investigation report" kind="loading" />}
    {job && <>
      <p className="agent-note">Investigation: {job.trigger} · Incident {job.incident_id ?? 'current-state test without incident reference'} · Snapshot tick {job.snapshot_tick ?? 'not available'}</p>
      {incidentId!==undefined && job.incident_id!==String(incidentId) && <p className="agent-note">This report refers to a different incident reference. Start AI Investigation to test the current selection.</p>}
      {(stale || historical || window?.run_id && window.run_id!==job.run_id || window?.end_tick!=null && job.snapshot_tick!=null && window.end_tick<job.snapshot_tick) && <div className="agent-context"><strong>{stale?'Earlier Simulation Run — Saved Investigation':'Historical Incident — Current-State Investigation'}</strong><p>The agent is testing the captured simulation state. These experiments do not reconstruct the original incident start.</p><p>Snapshot tick {job.snapshot_tick ?? 'not available'}{window?.start_tick!=null ? ` · Incident observations ${window.start_tick}–${window.end_tick ?? window.start_tick}` : ''}. {stale?'These findings belong to a different run and are not current-run results.':''}</p>{window?.run_id && window.run_id!==job.run_id && <p>The incident and snapshot belong to different runs; their tick numbers are not a single timeline.</p>}</div>}
      {job.status==='investigating' && <div role="status" className="agent-working"><strong>{stages[job.stage] ?? label(job.stage)}</strong><p>{job.completed_experiments} completed experiments. Progress is reported by the backend; no time estimate is inferred.</p></div>}
      {job.reason && !report && <p>{job.reason}</p>}{job.error && <p role="alert">{job.error}</p>}
      {report && <AgentConclusion report={report} />}
      {steps.length>0 && <section className="agent-timeline" aria-label="Investigation Timeline"><h3>Investigation Timeline</h3><ol>{steps.map(step=><li key={step.step}><h4>Step {step.step} — {interventionNames[step.intervention_id] ?? label(step.intervention_id)}</h4><p>{step.selection_reason}</p><p><strong>{outcomeLabel(step.intervention_outcome)}</strong> · {step.execution_status} · Virtual ticks {step.start_tick ?? '—'}–{step.end_tick==null?'—':step.end_tick-1}</p><p>{step.decision_afterward.explanation}</p>{step.decision_afterward.next_intervention && <p>Next selected test: {interventionNames[step.decision_afterward.next_intervention] ?? label(step.decision_afterward.next_intervention)}</p>}{step.exclusion_reason && <p>{step.exclusion_reason}</p>}</li>)}</ol></section>}
      {steps.length>0 && <AgentMeasurements steps={steps} />}
      {report && <details className="agent-technical"><summary>View Technical Investigation Report</summary><dl className="detail-dl"><div><dt>Investigation</dt><dd>{job.id}</dd></div><div><dt>Captured run / snapshot tick</dt><dd>{report.run_id} / {report.snapshot_tick}</dd></div><div><dt>Stopping reason</dt><dd>{label(report.stopping_reason)}</dd></div><div><dt>Work charged / budget</dt><dd>{report.branch_ticks_charged} / {report.budget.max_branch_ticks} branch-ticks</dd></div><div><dt>Experiment duration</dt><dd>{report.budget.duration_ticks} ticks per branch</dd></div></dl>
        {steps.map(step=><details key={step.experiment_id}><summary>{interventionNames[step.intervention_id]} — {step.experiment_id}</summary><p>Comparable: {step.comparable ? 'yes' : 'no'}. {step.exclusion_reason}</p><p>Possible explanations: {step.related_hypotheses.map(h=>h.explanation).join(' / ')}</p><ul>{step.relevant_evidence.map((item,index)=><li key={index}>Tick {item.tick} · {signalNames[item.signal] ?? label(item.signal)}: {String(item.value)} {item.unit ?? ''}{item.threshold==null?'':` (existing rule limit ${item.threshold})`} · {item.evidence_ids.join(', ') || 'No persisted evidence ID'} · {item.provenance.join(', ')}</li>)}</ul>{step.limitations.map(text=><p key={text}>{text}</p>)}</details>)}
        {report.initial_ai_assessment.original_model_records.map(record=><details key={record.model}><summary>Original {label(record.model)} model output · {label(record.scope)}</summary>{Object.entries(record.original_fields).map(([key,value])=><p key={key}>{label(key)}: {value==null?'Not available':String(value)}</p>)}{record.reported_candidates.map((candidate,index)=><p key={index}>{candidate.label}: model-reported score {candidate.model_score}. Not a new investigation probability.</p>)}</details>)}
        <p>At most 256 latest recorded residuals enter the approved context; full incident history remains in the incident API.</p><h4>Limitations and Remaining Uncertainty</h4>{report.evidence_fusion.limitations.map(text=><p key={text}>{text}</p>)}
      </details>}
    </>}
    <details className="agent-history"><summary>Recent Agent Investigations ({history.length})</summary><p className="agent-note">Up to 20 process-local records. Earlier-run results retain their original identity.</p>{history.length ? <ul>{history.map(item=><li key={item.id}><button className="button button-quiet" type="button" onClick={()=>{setSelected(item.id);setFollowLatest(false)}}>{label(item.status)} · {item.trigger} · Snapshot {item.snapshot_tick ?? '—'}{item.stale || item.run_id!==currentRun?' · Earlier run':''}</button><small>{item.incident_id ?? 'Current-state investigation'} · {item.created_at}</small></li>)}</ul> : <p>No agent investigations recorded.</p>}</details>
  </Card>
}

function AgentConclusion({report}:{report:AgentReport}) {
  const assessment=report.final_assessment
  const savedStage=report.initial_ai_assessment.original_model_records.find(record=>record.model==='stage_b')
  const recordedNature=savedStage?.original_fields.nature_verdict
  const recordedOrigin=savedStage?.original_fields.origin
  const stageNature=report.initial_ai_assessment.stage_b_nature ?? (typeof recordedNature==='string'?recordedNature:'Not available')
  const stageOrigin=report.initial_ai_assessment.stage_b_origin ?? (typeof recordedOrigin==='string'?recordedOrigin:'Not available')
  const stageScope=savedStage ? ` (${savedStage.scope==='current'?'current':'recorded incident window'}, ${String(savedStage.original_fields.status ?? 'status unavailable')})` : ''
  return <section className={`agent-conclusion ${assessment.intervention_effectiveness==='Intervention supported'?'':'agent-conclusion-warning'}`} aria-label="Final Investigation Assessment"><p className="eyebrow">FINAL INVESTIGATION ASSESSMENT</p><h3>{assessment.intervention_effectiveness}</h3><p>{report.stopping_explanation}</p><div className="agent-assessments"><div><h4>Initial AI Assessment</h4><p>Phase 1: {report.initial_ai_assessment.phase1_prediction ?? 'Not available'}<br />Stage B{stageScope}: {stageNature} · {stageOrigin}</p></div><div><h4>Autonomous Experimental Findings</h4><p>{report.executed_experiments} completed experiment{report.executed_experiments===1?'':'s'} · {report.attempted_experiments} attempt{report.attempted_experiments===1?'':'s'}</p><p>Most useful tested intervention: {assessment.most_useful_tested_intervention ? interventionNames[assessment.most_useful_tested_intervention] : 'Not distinguishable'}</p></div><div><h4>Remaining Uncertainty</h4><p>Source evidence: <strong>{assessment.source_evidence_assessment}</strong></p><p>{assessment.reason}</p></div></div><ul>{report.recommended_next_actions.map(action=><li key={action}>{action}</li>)}</ul></section>
}

function AgentMeasurements({steps}:{steps:AgentStep[]}) {
  const [index,setIndex]=useState(0)
  const [metric,setMetric]=useState('inverter_actual_kw')
  const focused=steps[Math.min(index,steps.length-1)]!
  const chart=useMemo<TelemetryPoint[]>(()=>focused.paired_telemetry.map(row=>({tick:row.tick,timestamp:`Tick ${row.tick}`,original:row.control[metric],intervention:row.experimental[metric]})),[focused,metric])
  return <section className="agent-measurements" aria-label="Autonomous experiment measurements"><h3>What Changed in the Virtual Experiment?</h3><div className="control-grid"><label className="field-label">Experiment<select aria-label="Agent experiment" value={Math.min(index,steps.length-1)} onChange={event=>setIndex(Number(event.target.value))}>{steps.map((step,i)=><option key={step.step} value={i}>Step {step.step} — {interventionNames[step.intervention_id]}</option>)}</select></label><label className="field-label">Measurement<select aria-label="Agent measurement" value={metric} onChange={event=>setMetric(event.target.value)}><option value="inverter_actual_kw">Actual inverter output (kW)</option><option value="delivered_kw">Delivered power (kW)</option></select></label></div><div className="agent-measures">{Object.entries(focused.physical_observations).map(([signal,value])=><div key={signal}><span>{signalNames[signal] ?? label(signal)}</span><strong>{shown(value.control_mean_excess)} → {shown(value.experimental_mean_excess)} {value.unit}</strong><small>Mean excess above the existing rule limit · original → intervention</small></div>)}<div><span>Delivered-energy difference</span><strong>{focused.delivered_energy_difference_kwh!=null && focused.delivered_energy_difference_kwh>0?'+':''}{shown(focused.delivered_energy_difference_kwh)}{focused.delivered_energy_difference_kwh==null?'':' kWh'}</strong><small>Intervention minus original behavior; not historical energy savings.</small></div></div>{chart.length ? <TimeSeriesChart data={chart} unit="kW" series={[{key:'original',label:'Original simulated behavior',color:'#a9622f'},{key:'intervention',label:'ShadowTwin intervention',color:'#17684f'}]} />:<EmptyState title="No paired experimental telemetry" detail="No missing measurements are invented." kind="unknown" />}</section>
}

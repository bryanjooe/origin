import { lazy, Suspense, useEffect, useState } from 'react'
import { ArrowRight, CircleAlert, Search, ShieldCheck, Wrench } from 'lucide-react'
import type { PageProps } from '../App'
import type { Incident, IncidentList } from '../types'
import { useAction, useResource } from '../hooks/useData'
import { ActionFeedback, Badge, Empty, ErrorNotice, Loading, PageHeading, Panel } from '../components/ui'
import { human, number, percent, sourceLabel } from '../utils/format'
const GridGraph = lazy(() => import('../components/GridGraph'))

export default function Investigation({ data, refresh, revision, offline }: PageProps) {
  const [selected, setSelected] = useState(() => new URLSearchParams(location.hash.split('?')[1]).get('id') ?? '')
  const list = useResource<IncidentList>('/incidents?limit=100', revision)
  const actualId = selected || data.incidents.items[0]?.id || list.data?.items[0]?.id || ''
  const detail = useResource<Incident>(actualId ? `/incidents/${encodeURIComponent(actualId)}` : null, revision)
  const action = useAction(refresh)
  useEffect(() => {
    const listener = () => { const id = new URLSearchParams(location.hash.split('?')[1]).get('id'); if (id) setSelected(id) }
    window.addEventListener('hashchange', listener); return () => window.removeEventListener('hashchange', listener)
  }, [])
  const incident = detail.data
  return <>
    <PageHeading eyebrow="FOLLOW THE EVIDENCE" title="Fault investigation" description="Connect unusual signals to likely sources, and understand what remains uncertain." />
    <div className="incident-picker"><Search size={17} /><label htmlFor="incident-choice">Investigate incident</label><select id="incident-choice" value={actualId} onChange={event => setSelected(event.target.value)}><option value="">Select an incident…</option>{list.data?.items.map(item => <option key={item.id} value={item.id}>{item.run_id.slice(0, 8)} · {item.local_id} · {sourceLabel(item.diagnosis.source)} · {item.status}</option>)}</select></div>
    {(detail.error || list.error) && <ErrorNotice>{detail.error ?? list.error}</ErrorNotice>}
    {!actualId ? <Panel><Empty title="No incidents to investigate">A confirmed anomaly will appear here. Open Live simulation to run a baseline and inject a fault.</Empty><div className="text-center pb-6"><a className="button primary" href="#simulation">Open simulation<ArrowRight size={15} /></a></div></Panel> : !incident ? <Loading>Loading incident evidence…</Loading> : <>
      <div className="diagnosis-banner"><div className="diagnosis-icon"><CircleAlert size={28} /></div><div><div className="eyebrow">REPRESENTATIVE SOURCE HYPOTHESIS</div><h2>{sourceLabel(incident.diagnosis.source)}</h2><p>{incident.diagnosis.confidence == null ? 'No accepted source prediction' : `${percent(incident.diagnosis.confidence)} classifier score · uncalibrated`}</p></div><div className="diagnosis-meta"><Badge value={incident.severity} /><Badge value={incident.status} /><span>Detected at tick {incident.detection_tick}</span><span>Representative tick {incident.representative_tick}</span></div></div>
      <div className="investigation-stats"><div><span>Peak anomaly score</span><strong>{number(incident.peak_anomaly_score, 4)}</strong></div><div><span>Alert confirmation delay</span><strong>{number(incident.confirmation_delay_seconds, 0)} <small>s</small></strong></div><div><span>Evidence observations</span><strong>{incident.evidence.length}</strong></div><div><span>Latest alert-time hypothesis</span><strong>{sourceLabel(incident.latest_diagnosis.source)}</strong></div></div>
      <div className="notice"><ShieldCheck size={17} /><span>Predictions and dependency paths are hypotheses. Temporal order and feature importance do not prove causation.</span></div>
      <Panel title="Suspected propagation" eyebrow="INTERACTIVE DEPENDENCY GRAPH" action={<span className="small-pill">Click a node or edge to inspect</span>}><Suspense fallback={<Loading />}><GridGraph graph={incident.graph} evidence={incident.evidence} /></Suspense><p className="chart-footnote">Historical incident view as of tick {incident.as_of_tick}. Highlighted intermediate components are potentially involved, not individually proven faulty.</p></Panel>
      <div className="dashboard-two-col"><Panel title="What the observations tell us" eyebrow="EXPLANATION"><div className="explanation-copy">{incident.explanation.why_flagged.map((text, i) => <p key={i}>{text}</p>)}<p>{incident.explanation.likely_source}</p>{incident.diagnosis.reasons.map(reason => <p className="text-amber" key={reason}>{reason}</p>)}</div><div className="evidence-list">{incident.explanation.deviations.map(item => <div key={item.evidence_id}><span className="evidence-bullet" /><p>{item.text}</p><small>{item.evidence_id}</small></div>)}</div><p className="fine-print">Residual checks are explicit rules alongside ML; they are not learned causal attribution.</p></Panel>
        <div className="space-y-5"><Panel title="Alternative explanations" eyebrow="COMPETING CANDIDATES">{incident.explanation.alternative_sources.length ? incident.explanation.alternative_sources.map(item => <div className="candidate-row" key={item.source}><div><span>{sourceLabel(item.source)}</span><div className="confidence-track"><i style={{ width: `${item.confidence * 100}%` }} /></div></div><strong>{percent(item.confidence)}</strong></div>) : <p className="muted">No trained source model or candidate scores are available.</p>}<p className="fine-print">Uncalibrated classifier scores, not probabilities of causation.</p></Panel>
          <Panel title="Next diagnostic checks"><ol className="checks-list">{incident.explanation.diagnostic_checks.map(check => <li key={check}>{check}</li>)}</ol>{incident.run_id === data.state.run_id && <button className="button full" disabled={action.busy || offline} onClick={() => action.act('/simulation/correct', undefined, 'Simulated correction applied; advance ticks to observe recovery')}><Wrench size={15} />Apply simulated correction</button>}<ActionFeedback error={action.error} message={action.message} /></Panel></div>
      </div>
      <Panel title="Observed symptom timeline" eyebrow="SEQUENCE, NOT CAUSAL PROOF"><div className="timeline">{incident.timeline.map((event, index) => <div className="timeline-item" key={`${event.tick}-${index}`}><div className="timeline-dot" /><span className="timeline-time">Tick {event.tick}</span><div><strong>{human(event.event)}</strong><p>{event.signal ? human(event.signal) : event.source ? sourceLabel(event.source) : event.event === 'alerts_cleared' ? 'The detector remained quiet for the recovery window.' : 'The confirmation rule was met.'}</p></div></div>)}</div><div className="notice subtle">{incident.explanation.recovery}</div></Panel>
    </>}
  </>
}

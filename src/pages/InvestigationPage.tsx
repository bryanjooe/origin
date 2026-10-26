import { useEffect, useState } from 'react'
import { Activity, ArrowRight, Check, CircleHelp, Crosshair, ShieldAlert, Wrench } from 'lucide-react'
import { DependencyGraph } from '../components/system/DependencyGraph'
import { Badge, Button, Card, EmptyState } from '../components/ui'
import { getSeverity, simulationLabel } from '../utils/status'
import { useApiResource } from '../hooks/useApiResource'
import { api } from '../services/api'
import type { EventRecord, IncidentDetail, IncidentGraph, IncidentSummary, SecurityAttribution, TopologyNode } from '../types/domain'
import { formatNumber, percent } from '../utils/data'

export function InvestigationPage() {
  const incidents = useApiResource('investigation-incidents', api.getIncidents, 8_000)
  const [incidentId, setIncidentId] = useState<string | number | null>(null)
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null)
  const [correcting, setCorrecting] = useState(false)
  const [correctionMessage, setCorrectionMessage] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    const firstIncident = incidents.data?.[0]
    if (incidentId === null && firstIncident) setIncidentId(firstIncident.id)
  }, [incidentId, incidents.data])

  const selectedIncident = incidents.data?.find((item) => String(item.id) === String(incidentId)) ?? null
  return (
    <>
      <div className="page-intro">
        <div><p className="eyebrow">FAULT RESPONSE / EVIDENCE REVIEW</p><h1>Fault investigation</h1><p className="intro-copy">Review likely sources and propagation evidence without treating a model output as proven cause.</p></div>
        {selectedIncident && <Badge severity={getSeverity(selectedIncident.severity)}>{selectedIncident.severity?.toUpperCase() ?? 'SEVERITY UNKNOWN'}</Badge>}
      </div>
      {incidents.error && !incidents.data && <EmptyState title="Incident data unavailable" detail={incidents.error} kind="error" action={<Button onClick={incidents.reload}>Retry</Button>} />}
      {incidents.loading && !incidents.data ? <EmptyState title="Loading incidents" kind="loading" /> : !incidents.error && !incidents.data?.length ? <EmptyState title="No incidents to investigate" detail="The incident endpoint returned no records." kind="unknown" /> : null}
      {selectedIncident && <InvestigationDetail key={String(selectedIncident.id)} incident={selectedIncident} selectedNode={selectedNode} onSelectNode={setSelectedNode} correcting={correcting} setCorrecting={setCorrecting} correctionMessage={correctionMessage} setCorrectionMessage={setCorrectionMessage} actionError={actionError} setActionError={setActionError} onChanged={incidents.reload} />}
      {incidents.data && incidents.data.length > 1 && <div className="incident-switcher"><span>INCIDENT</span>{incidents.data.map((incident) => <button key={incident.id} className={String(incident.id) === String(incidentId) ? 'selected' : ''} onClick={() => { setIncidentId(incident.id); setSelectedNode(null); setCorrectionMessage(null) }}>{incident.title ?? `${incident.source ?? 'Incident'} · ${incident.id}`}</button>)}</div>}
    </>
  )
}

function InvestigationDetail({
  incident: summary,
  selectedNode,
  onSelectNode,
  correcting,
  setCorrecting,
  correctionMessage,
  setCorrectionMessage,
  actionError,
  setActionError,
  onChanged,
}: {
  incident: IncidentSummary
  selectedNode: TopologyNode | null
  onSelectNode: (node: TopologyNode | null) => void
  correcting: boolean
  setCorrecting: (value: boolean) => void
  correctionMessage: string | null
  setCorrectionMessage: (value: string | null) => void
  actionError: string | null
  setActionError: (value: string | null) => void
  onChanged: () => void
}) {
  const detail = useApiResource<IncidentDetail>(`incident-detail-${summary.id}`, () => api.getIncident(summary.id))
  const graph = useApiResource<IncidentGraph>(`incident-graph-${summary.id}`, () => api.getIncidentGraph(summary.id))
  const incident = detail.data
  const candidates = incident?.candidates ?? []
  const confidence = percent(incident?.confidence ?? summary.confidence)

  async function applyCorrection() {
    setCorrecting(true)
    setActionError(null)
    setCorrectionMessage(null)
    try {
      const response = await api.applyCorrection(summary.id)
      setCorrectionMessage(response.message ?? 'Simulation-only corrective action accepted by the API.')
      onChanged()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Corrective action could not be applied.')
    } finally {
      setCorrecting(false)
    }
  }

  return (
    <>
      {detail.error && <div className="inline-error" role="alert">Incident detail unavailable: {detail.error}</div>}
      <div className="investigation-summary">
        <Card title={incident?.title ?? `Incident ${summary.id}`} eyebrow="INCIDENT / SUMMARY">
          {detail.loading && !incident ? <EmptyState title="Loading incident detail" kind="loading" /> : incident ? <><p className="incident-description">{incident.summary ?? 'No incident summary was provided by the API.'}</p><div className="summary-meta"><span>INCIDENT ID <strong>{summary.id}</strong></span><span>STATUS <strong>{simulationLabel(summary.status)}</strong></span><span>FIRST SEEN <strong>{summary.timestamp ?? summary.started_at ?? 'UNKNOWN'}</strong></span></div></> : <EmptyState title="Summary unavailable" detail="The API did not return incident details." kind="unknown" />}
        </Card>
        <Card title="Model assessment" eyebrow="ML PREDICTION / NOT GROUND TRUTH" className="prediction-card">
          <div className="prediction-source"><div><span className="small-label">PREDICTED SOURCE</span><strong>{summary.predicted_source ?? 'Unknown / insufficient evidence'}</strong></div><CircleHelp size={18} aria-hidden="true" /></div>
          <div className="confidence-line"><span>Confidence</span><strong>{confidence === undefined ? 'Unknown' : `${formatNumber(confidence, 1)}%`}</strong></div>
          {summary.anomaly_score !== null && summary.anomaly_score !== undefined ? <div className="score-line"><span>Anomaly score</span><code>{formatNumber(summary.anomaly_score, 3)}</code></div> : <p className="muted-small">Anomaly score was not returned.</p>}
          {summary.ground_truth && <div className="ground-truth"><span>INJECTED FAULT · GROUND TRUTH</span><strong>{summary.ground_truth.source ?? summary.ground_truth.label ?? summary.ground_truth.fault ?? 'Provided, label unavailable'}</strong></div>}
          <p className="uncertainty-note">A prediction is a likely source, not a proven root cause.</p>
        </Card>
      </div>

      <SecurityAttributionCard attribution={incident?.security_attribution} loading={detail.loading && !incident} />

      <div className="two-column-grid">
        <Card title="Propagation graph" eyebrow="KNOWN DEPENDENCIES / SUSPECTED PATHS" action={<span className="micro-label">SELECT A NODE FOR DETAILS</span>}>
          {graph.loading && !graph.data ? <EmptyState title="Loading propagation graph" kind="loading" /> : graph.error ? <EmptyState title="Propagation graph unavailable" detail={graph.error} kind="error" action={<Button onClick={graph.reload}>Retry</Button>} /> : graph.data?.nodes.length ? <><DependencyGraph nodes={graph.data.nodes} edges={graph.data.edges} onNodeSelect={onSelectNode} selectedNode={selectedNode?.id} height={365} /><div className="graph-legend"><span><i className="solid-key" />Known dependency</span><span><i className="dashed-key" />Suspected propagation</span><small>Suspected paths are uncertain.</small></div></> : <EmptyState title="Graph unavailable" detail="No graph nodes were returned for this incident." kind="unknown" />}
        </Card>
        <div className="stacked-panels">
          <Card title="Alternative candidates" eyebrow="MODEL / CANDIDATES">
            {detail.loading && !incident ? <EmptyState title="Loading candidates" kind="loading" /> : candidates.length ? <>{candidates.length > 1 && <p className="muted-small">Multiple candidates were returned; the likely source remains uncertain.</p>}<div className="candidate-list">{candidates.map((candidate, index) => <div className="candidate-row" key={`${candidate.source ?? candidate.component}-${index}`}><span className="candidate-rank">0{index + 1}</span><strong>{candidate.source ?? candidate.component ?? 'Unknown source'}</strong><code>{percent(candidate.confidence ?? candidate.score) === undefined ? '—' : `${formatNumber(percent(candidate.confidence ?? candidate.score), 1)}%`}</code></div>)}</div></> : <EmptyState title="No alternative candidates" detail="The model did not return candidates for this incident." kind="unknown" />}
          </Card>
          <Card title="Evidence and checks" eyebrow="DIAGNOSTIC / REVIEW">
            {detail.loading && !incident ? <EmptyState title="Loading evidence" kind="loading" /> : <><EvidenceList evidence={incident?.evidence ?? []} /><ResidualChecks evidence={incident?.residual_checks ?? []} /><DiagnosticList checks={incident?.diagnostic_checks ?? []} /></>}
          </Card>
        </div>
      </div>

      <div className="two-column-grid investigation-bottom">
        <Card title="Symptom timeline" eyebrow="SEQUENCE / EVENTS">
          {detail.loading && !incident ? <EmptyState title="Loading timeline" kind="loading" /> : incident?.timeline?.length ? <div className="timeline-list">{incident.timeline.map((event, index) => <TimelineRow key={event.id ?? `${event.timestamp}-${index}`} event={event} />)}</div> : <EmptyState title="No symptom timeline" detail="The incident response did not include timeline entries." kind="unknown" />}
        </Card>
        <Card title="Affected downstream components" eyebrow="IMPACT / LIKELY">
          {graph.data?.affected_downstream?.length ? <ul className="simple-list">{graph.data.affected_downstream.map((component) => <li key={component}><ArrowRight size={13} />{component}<span>Likely affected</span></li>)}</ul> : <EmptyState title="Downstream impact unknown" detail="No affected-component list was provided by the graph API." kind="unknown" />}
          <Button variant="primary" icon={<Wrench size={14} />} loading={correcting} disabled={correcting || !incident} onClick={() => void applyCorrection()} className="correction-button">Apply simulated corrective action</Button>
          <p className="control-footnote"><ShieldAlert size={13} />Simulation-only. This does not operate physical equipment.</p>
          {correctionMessage && <p className="success-message" role="status"><Check size={14} />{correctionMessage}</p>}
          {actionError && <p className="inline-error" role="alert">{actionError}</p>}
        </Card>
      </div>

      {selectedNode && <NodeDetail node={selectedNode} onClose={() => onSelectNode(null)} />}
    </>
  )
}

function SecurityAttributionCard({ attribution, loading }: { attribution?: SecurityAttribution; loading: boolean }) {
  return <Card title="Fault vs attack assessment" eyebrow="STAGE B / SECURITY CLASSIFIER" className="security-attribution-card">
    {loading ? <EmptyState title="Loading security assessment" kind="loading" /> : !attribution?.available ? <EmptyState title="Security assessment unavailable" detail={attribution?.reason ?? 'The backend did not return a Stage B prediction for this incident.'} kind="unknown" /> : <>
      <div className="security-verdict-row">
        <div><span className="small-label">NATURE · MODEL PREDICTION</span><strong>{attribution.nature_verdict || 'Undetermined'}</strong><p>Confidence {attribution.nature_confidence == null ? 'Unknown' : `${formatNumber(percent(attribution.nature_confidence) ?? attribution.nature_confidence * 100, 1)}%`}</p></div>
        <div><span className="small-label">ORIGIN LAYER · MODEL PREDICTION</span><strong>{attribution.origin ?? 'Unknown / insufficient evidence'}</strong><p>Confidence {attribution.origin_confidence == null ? 'Unknown' : `${formatNumber(percent(attribution.origin_confidence) ?? attribution.origin_confidence * 100, 1)}%`}</p></div>
        {attribution.inference_tick !== undefined && <div><span className="small-label">CAUSAL WINDOW</span><strong>{attribution.window_ticks ?? '—'} ticks</strong><p>Inference at tick {attribution.inference_tick}</p></div>}
      </div>
      {attribution.origin_candidates?.length ? <div className="candidate-list security-origin-candidates">{attribution.origin_candidates.slice(0, 3).map((candidate, index) => <div className="candidate-row" key={`${candidate.layer}-${index}`}><span className="candidate-rank">0{index + 1}</span><strong>{candidate.layer}</strong><code>{formatNumber(percent(candidate.confidence) ?? candidate.confidence * 100, 1)}%</code></div>)}</div> : null}
      <p className="uncertainty-note">{attribution.evidence?.statement ?? 'Indicators from observable telemetry are not proof of intent or a proven root cause.'}</p>
      {attribution.evidence?.uncertainty && <p className="muted-small">{attribution.evidence.uncertainty}</p>}
      <div className="security-evidence-grid">
        <AttributionObservations title="Points toward attack" items={attribution.evidence?.points_toward_attack ?? []} />
        <AttributionObservations title="Points toward fault" items={attribution.evidence?.points_toward_fault ?? []} />
        <AttributionObservations title="Ambiguous indicators" items={attribution.evidence?.ambiguous ?? []} />
      </div>
    </>}
  </Card>
}

function AttributionObservations({ title, items }: { title: string; items: NonNullable<SecurityAttribution['evidence']>['ambiguous'] }) {
  return <section className="security-observations"><h3>{title}</h3>{items?.length ? <ul>{items.map((item, index) => <li key={`${item.name}-${index}`}><span>{item.name}</span><strong>{String(item.value)}{item.unit ? ` ${item.unit}` : ''}</strong></li>)}</ul> : <p className="muted-small">No observations were returned for this category.</p>}</section>
}

function EvidenceList({ evidence }: { evidence: NonNullable<IncidentDetail['evidence']> }) {
  if (!evidence.length) return <EmptyState title="No evidence returned" detail="Evidence is not inferred or fabricated when the API omits it." kind="unknown" />
  return <div className="evidence-list">{evidence.map((item, index) => <div className="evidence-row" key={item.id ?? index}><Crosshair size={14} /><div><strong>{item.type ?? item.source ?? 'Evidence'}</strong><p>{item.description ?? (item.value === undefined ? 'Description unavailable.' : String(item.value))}</p>{item.timestamp && <small>{item.timestamp}</small>}</div></div>)}</div>
}

function DiagnosticList({ checks }: { checks: string[] }) {
  return <div className="diagnostic-block"><h3>Suggested diagnostic checks</h3>{checks.length ? <ul className="simple-list">{checks.map((check) => <li key={check}><Check size={13} />{check}</li>)}</ul> : <p className="muted-small">No diagnostic checks were provided by the API.</p>}</div>
}

function ResidualChecks({ evidence }: { evidence: NonNullable<IncidentDetail['residual_checks']> }) {
  return <div className="diagnostic-block"><h3>Rule-based residual checks</h3>{evidence.length ? <EvidenceList evidence={evidence} /> : <p className="muted-small">No rule-based residual checks were provided by the API. ML predictions are shown separately above.</p>}</div>
}

function TimelineRow({ event }: { event: EventRecord }) {
  return <div className="timeline-row"><span className="timeline-dot" /><time>{event.timestamp ?? event.time ?? (event.simulation_time !== undefined ? `T+${event.simulation_time}` : 'TIME UNKNOWN')}</time><div><strong>{event.message ?? event.description ?? event.event ?? event.type ?? 'Event'}</strong><p>{event.details ? JSON.stringify(event.details) : 'Event details unavailable.'}</p></div></div>
}

function NodeDetail({ node, onClose }: { node: TopologyNode; onClose: () => void }) {
  const telemetry = node.telemetry ?? {}
  const events = node.events ?? []
  return <aside className="node-detail" aria-label={`${node.label ?? node.id} component details`}>
    <div className="node-detail-heading"><div><span className="eyebrow">COMPONENT / TELEMETRY</span><h3>{node.label ?? node.id}</h3></div><Button variant="quiet" onClick={onClose}>Close</Button></div>
    {Object.keys(telemetry).length ? <dl className="detail-dl">{Object.entries(telemetry).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl> : <EmptyState title="No component telemetry" detail="The graph response did not include telemetry for this node." kind="unknown" />}
    <h4><Activity size={13} />Component events</h4>
    {events.length ? <div className="component-events">{events.map((event, index) => <p key={event.id ?? index}>{event.timestamp ?? event.time ?? 'TIME UNKNOWN'} · {event.message ?? event.description ?? event.event ?? 'Event'}</p>)}</div> : <p className="muted-small">No component events were returned.</p>}
  </aside>
}

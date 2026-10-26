import { useEffect, useState } from 'react'
import { ArrowRight, Check, CircleHelp, Crosshair, ShieldAlert, Wrench } from 'lucide-react'
import { Link } from 'react-router-dom'
import { DependencyGraph } from '../components/system/DependencyGraph'
import { Badge, Button, Card, EmptyState } from '../components/ui'
import { useApiResource } from '../hooks/useApiResource'
import { api } from '../services/api'
import type { IncidentDetail, IncidentSummary, SecurityAttribution, TopologyNode } from '../types/domain'
import { formatNumber, percent } from '../utils/data'
import { getSeverity } from '../utils/status'

type Correction = { incidentId: string | number; tick?: number; actions?: Array<{ label: string; detail: string }> }

export function InvestigationPage() {
  const incidents = useApiResource('investigation-incidents', api.getActiveIncidents, 8_000)
  const [incidentId, setIncidentId] = useState<string | number | null>(null)
  const [correction, setCorrection] = useState<Correction | null>(null)
  const [correctionError, setCorrectionError] = useState<string | null>(null)
  const active = incidents.data ?? []
  const selected = active.find((item) => String(item.id) === String(incidentId)) ?? active[0] ?? null

  useEffect(() => {
    if (!active.some((item) => String(item.id) === String(incidentId))) setIncidentId(active[0]?.id ?? null)
  }, [active, incidentId])

  return <>
    <div className="page-intro">
      <div><p className="eyebrow">FAULT RESPONSE</p><h1>Fault investigation</h1><p className="intro-copy">Review an active incident, apply a simulation-only correction, and find the full record later in history.</p></div>
      <div className="intro-actions"><Link className="button button-secondary" to="/incidents">Incident history <ArrowRight size={14} aria-hidden="true" /></Link></div>
    </div>

    {incidents.error && !incidents.data && <EmptyState title="Incident data unavailable" detail={incidents.error} kind="error" action={<Button onClick={incidents.reload}>Retry</Button>} />}
    {incidents.loading && !incidents.data && <EmptyState title="Checking for active incidents" kind="loading" />}
    {correction && <CorrectionComplete correction={correction} />}
    {correctionError && <div className="inline-error" role="alert">Correction failed: {correctionError}</div>}
    {incidents.data && active.length === 0 && !correction && null}
    {active.length > 1 && <div className="incident-switcher"><span>ACTIVE INCIDENT</span>{active.map((incident) => <button type="button" key={incident.id} className={String(incident.id) === String(selected?.id) ? 'selected' : ''} onClick={() => setIncidentId(incident.id)}>{incident.title ?? `Incident ${incident.id}`}</button>)}</div>}
    {selected && <InvestigationDetail key={String(selected.id)} incident={selected} onCorrect={async () => {
      setCorrectionError(null)
      try {
        const result = await api.applyCorrection(selected.id)
        if (!result.correction_applied) throw new Error('The backend did not confirm that a simulated correction was applied.')
        setCorrection({ incidentId: selected.id, tick: result.correction_tick, actions: result.actions_applied })
        await incidents.reload()
      } catch (error) {
        setCorrectionError(error instanceof Error ? error.message : 'The correction could not be applied.')
      }
    }} />}
  </>
}

function CorrectionComplete({ correction }: { correction: Correction }) {
  return <Card className="correction-complete" title="Incident handled in simulation" eyebrow="SIMULATED CORRECTION / COMPLETE">
    <p className="incident-description">The simulator applied the actions below and moved incident <strong>{correction.incidentId}</strong> to resolved. No physical equipment was changed.</p>
    {correction.tick !== undefined && <p className="correction-tick">CORRECTION TICK <strong>{correction.tick}</strong></p>}
    {correction.actions?.length ? <ul className="applied-action-list">{correction.actions.map((action, index) => <li key={`${action.label}-${index}`}><Check size={15} aria-hidden="true" /><div><strong>{action.label}</strong><span>{action.detail}</span></div></li>)}</ul> : <p className="muted-small">The backend confirmed the correction but did not return an action breakdown. The incident detail remains available in history.</p>}
    <Link className="button button-secondary" to="/incidents">View incident history <ArrowRight size={14} aria-hidden="true" /></Link>
  </Card>
}

function InvestigationDetail({ incident, onCorrect }: { incident: IncidentSummary; onCorrect: () => Promise<void> }) {
  const detail = useApiResource<IncidentDetail>(`incident-detail-${incident.id}`, () => api.getIncident(incident.id), 3_000)
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null)
  const [correcting, setCorrecting] = useState(false)
  const data = detail.data
  const graph = data?.graph
  const attribution = data?.security_attribution
  const predictedOrigin = attribution?.available ? attribution.origin : data?.predicted_source
  const confidenceValue = attribution?.available ? attribution.origin_confidence : data?.confidence
  const confidence = percent(confidenceValue ?? null)
  const predictionUnavailable = !attribution?.available && !data?.predicted_source
  const incidentSummary = predictionUnavailable && data?.detection_method === 'rules'
    ? 'No model source prediction is available. The origin remains Unknown or insufficient evidence.'
    : data?.summary ?? 'The backend did not provide a written summary for this incident.'

  async function correct() {
    setCorrecting(true)
    try { await onCorrect() } finally { setCorrecting(false) }
  }

  return <>
    {detail.error && <div className="inline-error" role="alert">Incident detail unavailable: {detail.error}</div>}
    <div className="investigation-summary compact-investigation-summary">
      <Card title={data?.title ?? incident.title ?? `Incident ${incident.id}`} eyebrow="ACTIVE INCIDENT">
        {detail.loading && !data ? <EmptyState title="Loading incident details" kind="loading" /> : <>
          <p className="incident-description">{incidentSummary}</p>
          <div className="summary-meta"><span>SEVERITY<strong><Badge severity={getSeverity(incident.severity)}>{incident.severity ?? 'Unknown'}</Badge></strong></span><span>STATUS<strong>{incident.status ?? 'Unknown'}</strong></span><span>FIRST SEEN<strong>{incident.timestamp ?? incident.started_at ?? 'Unknown'}</strong></span></div>
          {data?.detection_method === 'rules' && <p className="muted-small">Detection came from observable residual rules. The ML detector is unavailable, so no model prediction is shown.</p>}
        </>}
      </Card>
      <Card title={predictionUnavailable ? 'Source assessment' : 'Likely source'} eyebrow={predictionUnavailable ? 'MODEL PREDICTION / UNAVAILABLE' : 'MODEL PREDICTION / UNCERTAIN'} className="prediction-card">
        <div className="prediction-source"><div><span className="small-label">PREDICTED ORIGIN</span><strong>{predictedOrigin ?? 'Unknown / insufficient evidence'}</strong></div><CircleHelp size={18} aria-hidden="true" /></div>
        <div className="confidence-line"><span>Confidence</span><strong>{confidence === undefined ? 'Unknown' : `${formatNumber(confidence, 1)}%`}</strong></div>
        {attribution?.nature_verdict && <p className="muted-small">Nature: {attribution.nature_verdict}{attribution.nature_confidence == null ? '' : ` · ${formatNumber((percent(attribution.nature_confidence) ?? attribution.nature_confidence * 100), 1)}% confidence`}</p>}
        {incident.ground_truth && <div className="ground-truth"><span>INJECTED SCENARIO · GROUND TRUTH</span><strong>{incident.ground_truth.source ?? incident.ground_truth.label ?? incident.ground_truth.fault ?? 'Label unavailable'}</strong></div>}
        <p className="uncertainty-note">{predictionUnavailable ? 'The model did not return a source prediction. The likely origin remains unknown until trained model output is available.' : 'This is a likely source from the model, not a proven root cause.'}</p>
      </Card>
    </div>

    <div className="investigation-workspace">
      <Card title="Microgrid and likely path" eyebrow="DEPENDENCIES / SUSPECTED PROPAGATION" action={<span className="micro-label">SELECT A COMPONENT FOR DETAILS</span>}>
        {detail.loading && !graph ? <EmptyState title="Loading microgrid graph" kind="loading" /> : detail.error && !graph ? <EmptyState title="Microgrid graph unavailable" detail={detail.error} kind="error" action={<Button onClick={detail.reload}>Retry</Button>} /> : graph?.nodes.length ? <>
          <DependencyGraph nodes={graph.nodes} edges={graph.edges} onNodeSelect={setSelectedNode} selectedNode={selectedNode?.id} height={520} />
          <div className="graph-legend"><span><i className="solid-key" />Known dependency</span><span><i className="dashed-key" />Suspected path</span></div>
          <p className="muted-small">Dashed paths are hypotheses based on returned evidence. They indicate what may be affected, not confirmed compromise.</p>
        </> : <EmptyState title="No graph data returned" kind="unknown" />}
      </Card>
      <div className="investigation-side-column">
        <Card title="Recorded evidence" eyebrow="OBSERVED SIGNALS">
          {detail.loading && !data ? <EmptyState title="Loading evidence" kind="loading" /> : data?.evidence?.length ? <div className="evidence-list">{data.evidence.map((item, index) => <div className="evidence-row" key={item.id ?? index}><Crosshair size={14} aria-hidden="true" /><div><strong>{item.type ?? item.source ?? 'Observation'}</strong><p>{item.description ?? (item.value === undefined ? 'Description unavailable.' : String(item.value))}</p>{item.timestamp && <small>{item.timestamp}</small>}</div></div>)}</div> : <EmptyState title="No evidence returned" detail="No observations are shown when the API does not provide them." kind="unknown" />}
          {data?.residual_checks?.length ? <details className="residual-details"><summary>Rule-based residual checks ({data.residual_checks.length})</summary><div className="evidence-list">{data.residual_checks.map((item, index) => <div className="evidence-row" key={item.id ?? index}><div><strong>{item.source ?? item.type ?? 'Residual check'}</strong><p>{item.description ?? 'Details unavailable.'}</p></div></div>)}</div></details> : null}
        </Card>
        <Card title="Apply correction" eyebrow="SIMULATION ONLY">
          <p className="incident-description">Stop active injected behavior and clear stale communication state in this simulation. The result is saved with the incident history.</p>
          <Button variant="primary" icon={<Wrench size={14} />} loading={correcting} disabled={correcting} onClick={() => void correct()} className="correction-button">Apply simulated fix</Button>
          <p className="control-footnote"><ShieldAlert size={13} aria-hidden="true" />Simulation-only action; no physical equipment is operated.</p>
        </Card>
      </div>
    </div>
    {selectedNode && <NodeDetail node={selectedNode} onClose={() => setSelectedNode(null)} />}
  </>
}

function NodeDetail({ node, onClose }: { node: TopologyNode; onClose: () => void }) {
  return <aside className="node-detail" aria-label={`${node.label ?? node.id} component details`}>
    <div className="node-detail-heading"><div><span className="eyebrow">COMPONENT</span><h3>{node.label ?? node.id}</h3></div><Button variant="quiet" onClick={onClose}>Close</Button></div>
    <p className="muted-small">{node.observed_symptom ? 'An observed abnormality is linked to this component.' : 'No direct abnormality is established for this component.'} Downstream relationships describe possible structural impact only.</p>
    {node.direct_evidence?.length ? <div className="evidence-list">{node.direct_evidence.slice(-6).reverse().map((item) => <div className="evidence-row" key={item.id}><Crosshair size={14} aria-hidden="true" /><div><strong>{item.signal ?? 'Recorded observation'}</strong><p>{item.description ?? 'Details unavailable.'}</p><small>Tick {item.tick ?? 'unknown'} · {typeof item.value === 'number' ? formatNumber(item.value, 3) : String(item.value ?? 'Value unavailable')} {item.unit ?? ''}</small></div></div>)}</div> : <EmptyState title="No component evidence" detail="The graph did not return direct observations for this component." kind="unknown" />}
    {Object.keys(node.telemetry ?? {}).length > 0 && <dl className="detail-dl">{Object.entries(node.telemetry ?? {}).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>}
  </aside>
}

// Kept as a compact reusable disclosure for callers that need the full Stage B assessment.
export function SecurityAttributionCard({ attribution, loading }: { attribution?: SecurityAttribution; loading: boolean }) {
  const status = attribution?.status === 'pending' ? 'Pending telemetry'
    : attribution?.status === 'insufficient_evidence' ? 'Insufficient evidence'
      : !attribution?.available ? 'Model unavailable'
        : attribution.nature_verdict ?? 'Analysis available'
  return <Card title="AI security assessment" eyebrow="MODEL INDICATORS / NOT PROOF">
    {loading ? <EmptyState title="Loading security assessment" kind="loading" /> : !attribution?.available
      ? <EmptyState title={status} detail={attribution?.reason ?? 'No security assessment was returned.'} kind="unknown" />
      : <><p className="incident-description">Nature: {attribution.nature_verdict ?? 'Undetermined'} · Origin: {attribution.origin ?? 'Unknown / insufficient evidence'}</p>
        <p className="muted-small">Confidence is {attribution.confidence_kind?.startsWith('uncalibrated') ? 'an uncalibrated model score' : 'reported by the model'}; these indicators do not prove intent.</p>
        {[['Points toward attack', attribution.evidence?.points_toward_attack], ['Points toward fault', attribution.evidence?.points_toward_fault], ['Ambiguous indicators', attribution.evidence?.ambiguous]].map(([heading, items]) => <section className="diagnostic-block" key={String(heading)}><h3>{String(heading)}</h3>{Array.isArray(items) && items.length ? <ul className="simple-list">{items.map((item, index) => <li key={`${item.name}-${index}`}>{item.name}<span>{String(item.value)}{item.unit ? ` ${item.unit}` : ''}</span></li>)}</ul> : <p className="muted-small">No observations returned.</p>}</section>)}
      </>}
  </Card>
}

import { useEffect, useMemo, useState } from 'react'
import { Download, Search, X } from 'lucide-react'
import { useApiResource } from '../hooks/useApiResource'
import { api } from '../services/api'
import type { IncidentDetail, IncidentSummary, Severity } from '../types/domain'
import { displayTime } from '../utils/data'
import { getSeverity } from '../utils/status'
import { Badge, Button, Card, DataTable, EmptyState, type TableColumn } from '../components/ui'

export function IncidentHistoryPage() {
  const incidents = useApiResource('incident-history', api.getIncidents, 12_000)
  const [query, setQuery] = useState('')
  const [severity, setSeverity] = useState('all')
  const [source, setSource] = useState('all')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [selected, setSelected] = useState<IncidentSummary | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  const sources = [...new Set((incidents.data ?? []).map((incident) => incident.source).filter((item): item is string => !!item))].sort()
  const rows = useMemo(() => (incidents.data ?? []).filter((incident) => {
    const text = `${incident.title ?? ''} ${incident.source ?? ''} ${incident.predicted_source ?? ''} ${incident.id} ${incident.status ?? ''}`.toLowerCase()
    const dateValue = incident.timestamp ?? incident.started_at
    const dateTime = dateValue ? new Date(dateValue).getTime() : Number.NaN
    const afterStart = !fromDate || (Number.isFinite(dateTime) && dateTime >= new Date(`${fromDate}T00:00:00`).getTime())
    const beforeEnd = !toDate || (Number.isFinite(dateTime) && dateTime <= new Date(`${toDate}T23:59:59.999`).getTime())
    return text.includes(query.toLowerCase()) && (severity === 'all' || getSeverity(incident.severity) === severity) && (source === 'all' || incident.source === source) && afterStart && beforeEnd
  }), [incidents.data, query, severity, source, fromDate, toDate])
  const columns: TableColumn<IncidentSummary>[] = [
    { key: 'time', header: 'Time', render: (row) => <span className="mono">{row.timestamp ?? row.started_at ?? 'Unknown time'}</span> },
    { key: 'severity', header: 'Severity', render: (row) => <Badge severity={getSeverity(row.severity)}>{row.severity ?? 'Unknown'}</Badge> },
    { key: 'source', header: 'Ground truth source', render: (row) => row.ground_truth?.source ?? row.source ?? 'Not provided by API' },
    { key: 'prediction', header: 'Model prediction', render: (row) => row.predicted_source ?? 'Unknown / insufficient evidence' },
    { key: 'status', header: 'Status', render: (row) => row.status ?? 'Unknown' },
  ]

  async function exportData(format: 'csv' | 'json') {
    setExportError(null)
    try {
      const blob = await api.exportReport(format)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `origin-incidents.${format}`
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 0)
      URL.revokeObjectURL(url)
    } catch (error) {
      setExportError(error instanceof Error ? error.message : 'Export failed.')
    }
  }

  return <>
    <div className="page-intro"><div><p className="eyebrow">OPERATIONS / RECORDS</p><h1>Incident history</h1><p className="intro-copy">Search and review returned incidents. Predictions and injected-fault labels are kept separate.</p></div><div className="intro-actions"><Button icon={<Download size={14} />} onClick={() => void exportData('csv')}>Export CSV</Button><Button icon={<Download size={14} />} onClick={() => void exportData('json')}>Export JSON</Button></div></div>
    {incidents.loading && !incidents.data && <EmptyState title="Loading incident history" kind="loading" />}
    {incidents.error && !incidents.data && <EmptyState title="Incident history unavailable" detail={incidents.error} kind="error" action={<Button onClick={incidents.reload}>Retry</Button>} />}
    {exportError && <div className="inline-error" role="alert">Export failed: {exportError}</div>}
    <Card title="Incidents" eyebrow={`${rows.length} MATCHING RECORDS`} action={incidents.data && <span className="micro-label">API-RETURNED RECORDS</span>}>
      <div className="filter-row">
        <label className="search-field"><Search size={15} aria-hidden="true" /><span className="sr-only">Search incidents</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search incident, source, ID…" /></label>
        <label className="filter-field"><span>Severity</span><select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="all">All severities</option>{(['normal', 'warning', 'critical', 'unknown'] as Severity[]).map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label className="filter-field"><span>Source</span><select value={source} onChange={(event) => setSource(event.target.value)}><option value="all">All sources</option>{sources.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label className="filter-field"><span>From</span><input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} /></label>
        <label className="filter-field"><span>To</span><input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} /></label>
      </div>
      {incidents.data && <DataTable rows={rows} columns={columns} rowKey={(row) => row.id} onRowClick={setSelected} empty={<EmptyState title="No matching incidents" detail="Change or clear your search and filters." />} />}
      {incidents.data?.length === 0 && <EmptyState title="No incidents recorded" detail="The API returned an empty incident history." kind="unknown" />}
    </Card>
    {selected && <IncidentDrawer incident={selected} onClose={() => setSelected(null)} />}
  </>
}

function IncidentDrawer({ incident, onClose }: { incident: IncidentSummary; onClose: () => void }) {
  const detail = useApiResource<IncidentDetail>(`history-detail-${incident.id}`, () => api.getIncident(incident.id))
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])
  return <div className="drawer-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><aside className="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
    <div className="drawer-heading"><div><p className="eyebrow">INCIDENT / DETAIL</p><h2 id="drawer-title">{incident.title ?? `Incident ${incident.id}`}</h2></div><Button variant="quiet" icon={<X size={17} />} title="Close incident details" onClick={onClose}>Close</Button></div>
    <div className="drawer-meta"><Badge severity={getSeverity(incident.severity)}>{incident.severity ?? 'Unknown severity'}</Badge><span className="mono">ID {incident.id}</span><span>{displayTime(incident.timestamp ?? incident.started_at)}</span></div>
    {detail.loading && !detail.data && <EmptyState title="Loading incident detail" kind="loading" />}
    {detail.error && <EmptyState title="Incident detail unavailable" detail={detail.error} kind="error" action={<Button onClick={detail.reload}>Retry</Button>} />}
    {detail.data && <div className="drawer-content"><DetailLine label="Ground truth source" value={detail.data.ground_truth?.source ?? detail.data.ground_truth?.fault ?? detail.data.ground_truth?.label ?? 'Not provided by API'} /><DetailLine label="Model prediction" value={detail.data.predicted_source ?? 'Unknown / insufficient evidence'} /><DetailLine label="Confidence" value={detail.data.confidence == null ? undefined : `${(detail.data.confidence <= 1 ? detail.data.confidence * 100 : detail.data.confidence).toFixed(1)}%`} /><DetailLine label="Anomaly score" value={detail.data.anomaly_score == null ? undefined : detail.data.anomaly_score.toFixed(3)} /><DetailLine label="Status" value={detail.data.status} /><p className="drawer-section-label">SUMMARY</p><p>{detail.data.summary ?? 'No summary returned.'}</p>{detail.data.ground_truth && <div className="ground-truth"><span>INJECTED FAULT · GROUND TRUTH</span><strong>{detail.data.ground_truth.source ?? detail.data.ground_truth.fault ?? detail.data.ground_truth.label ?? 'Label unavailable'}</strong></div>}{detail.data.correction_applied?.simulation_only && <section className="history-correction"><p className="drawer-section-label">SIMULATED CORRECTION · HANDLED</p><p>This incident was marked resolved by a simulation-only correction at tick {detail.data.correction_applied.tick ?? 'unknown'}. No physical equipment was changed.</p>{detail.data.correction_applied.actions_applied?.length ? <ul className="applied-action-list">{detail.data.correction_applied.actions_applied.map((action, index) => <li key={`${action.label}-${index}`}><span className="history-check">✓</span><div><strong>{action.label}</strong><span>{action.detail}</span></div></li>)}</ul> : <p className="muted-small">No action breakdown was saved for this record.</p>}</section>}<p className="drawer-section-label">EVIDENCE</p>{detail.data.evidence?.length ? detail.data.evidence.map((item, index) => <div className="evidence-row" key={item.id ?? index}><div><strong>{item.type ?? item.source ?? 'Evidence'}</strong><p>{item.description ?? (item.value === undefined ? 'Description unavailable' : String(item.value))}</p></div></div>) : <EmptyState title="No evidence returned" kind="unknown" />}</div>}
  </aside></div>
}

function DetailLine({ label, value }: { label: string; value?: string }) {
  return <div className="detail-line"><span>{label}</span><strong>{value ?? 'Unknown'}</strong></div>
}

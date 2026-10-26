import { useEffect, useState } from 'react'
import { ArrowUpRight, ChevronLeft, ChevronRight, Download, Search } from 'lucide-react'
import type { PageProps } from '../App'
import type { IncidentList } from '../types'
import { useResource } from '../hooks/useData'
import { exportUrl, query } from '../services/api'
import { Badge, Empty, ErrorNotice, Loading, PageHeading, Panel } from '../components/ui'
import { percent, sourceLabel, wallTime } from '../utils/format'

export default function History({ revision }: PageProps) {
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [status, setStatus] = useState('')
  const [severity, setSeverity] = useState('')
  const [source, setSource] = useState('')
  const [offset, setOffset] = useState(0)
  useEffect(() => { const timer = setTimeout(() => { setDebounced(search); setOffset(0) }, 250); return () => clearTimeout(timer) }, [search])
  const params = query({ search: debounced, status, severity, source, offset, limit: 15 })
  const result = useResource<IncidentList>(`/incidents?${params}`, revision)
  return <>
    <PageHeading eyebrow="A RECORD OF WHAT HAPPENED" title="Incident history" description="Review persisted investigations across runs, including resolved and interrupted incidents." action={<div className="button-group"><a className="button" href={exportUrl('incidents', 'csv')} download><Download size={15} />CSV</a><a className="button" href={exportUrl('incidents', 'json')} download><Download size={15} />JSON</a></div>} />
    <Panel><div className="filter-bar"><div className="search-input"><Search size={16} /><input aria-label="Search incident history" placeholder="Search incident ID or source…" value={search} onChange={event => setSearch(event.target.value)} /></div>
      <select aria-label="Filter incident status" value={status} onChange={event => { setStatus(event.target.value); setOffset(0) }}><option value="">All statuses</option>{['open', 'resolved', 'interrupted'].map(value => <option key={value}>{value}</option>)}</select>
      <select aria-label="Filter incident severity" value={severity} onChange={event => { setSeverity(event.target.value); setOffset(0) }}><option value="">All severities</option><option value="warning">Warning</option><option value="critical">Critical</option></select>
      <select aria-label="Filter predicted source" value={source} onChange={event => { setSource(event.target.value); setOffset(0) }}><option value="">All sources</option>{['sensor', 'communication', 'controller', 'firmware', 'inverter', 'unknown'].map(value => <option key={value} value={value}>{sourceLabel(value)}</option>)}</select>
    </div>
    {result.error && <ErrorNotice>{result.error}</ErrorNotice>}
    {!result.data ? <Loading /> : !result.data.total ? <Empty title="No matching incidents">Confirmed incidents persist here across resets and backend restarts.</Empty> : <><div className="table-scroll"><table className="history-table"><thead><tr><th>Incident / run</th><th>Recorded</th><th>Severity</th><th>Predicted source</th><th>Status</th><th>Confirmation</th><th /></tr></thead><tbody>{result.data.items.map(item => <tr key={item.id}><td><strong>{item.local_id}</strong><small>{item.run_id.slice(0, 8)} · Tick {item.detection_tick}</small></td><td>{wallTime(item.created_at)}</td><td><Badge value={item.severity} /></td><td>{sourceLabel(item.diagnosis.source)}<small>{item.diagnosis.confidence == null ? 'No accepted source score' : `${percent(item.diagnosis.confidence)} · uncalibrated`}</small></td><td><Badge value={item.status} /></td><td>{item.confirmation_delay_seconds}s</td><td><a className="icon-button" aria-label={`Investigate ${item.id}`} href={`#investigation?id=${encodeURIComponent(item.id)}`}><ArrowUpRight size={17} /></a></td></tr>)}</tbody></table></div><div className="pagination"><span>{offset + 1}–{Math.min(offset + 15, result.data.total)} of {result.data.total} incidents</span><div className="button-group"><button className="button small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 15))}><ChevronLeft size={15} />Previous</button><button className="button small" disabled={offset + 15 >= result.data.total} onClick={() => setOffset(offset + 15)}>Next<ChevronRight size={15} /></button></div></div></>}
    </Panel><p className="fine-print">Confirmation delay measures time from the first observed alert, not hidden fault onset. Recorded timestamps use your browser’s local timezone. Exports include all history up to 5,000 rows, independently of the filters above.</p>
  </>
}

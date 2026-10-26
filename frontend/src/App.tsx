import { lazy, Suspense, useEffect, useState } from 'react'
import { Activity, ArrowUpRight, BatteryCharging, ChevronRight, FlaskConical, LayoutDashboard, Leaf, Menu, Network, ShieldCheck, SlidersHorizontal, X, History } from 'lucide-react'
import { useLiveData } from './hooks/useData'
import { Badge, ErrorNotice, Loading } from './components/ui'
import { simTime } from './utils/format'
import type { LiveData } from './types'

const Overview = lazy(() => import('./pages/Overview'))
const Simulation = lazy(() => import('./pages/Simulation'))
const Investigation = lazy(() => import('./pages/Investigation'))
const Sustainability = lazy(() => import('./pages/Sustainability'))
const IncidentHistory = lazy(() => import('./pages/History'))
const Evaluation = lazy(() => import('./pages/Evaluation'))
const navigation = [
  { id: 'overview', label: 'System overview', icon: LayoutDashboard },
  { id: 'simulation', label: 'Live simulation', icon: SlidersHorizontal },
  { id: 'investigation', label: 'Fault investigation', icon: Network },
  { id: 'sustainability', label: 'Sustainability', icon: Leaf },
  { id: 'history', label: 'Incident history', icon: History },
  { id: 'evaluation', label: 'Model evaluation', icon: FlaskConical },
]
export interface PageProps { data: LiveData; refresh: () => void; revision: number; offline: boolean }

export default function App() {
  const [route, setRoute] = useState(() => location.hash.slice(1).split('?')[0] || 'overview')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 640px)').matches)
  const { data, error, updatedAt, refresh, revision } = useLiveData()
  useEffect(() => { const listener = () => { setRoute(location.hash.slice(1).split('?')[0] || 'overview'); setMobileOpen(false); window.scrollTo({ top: 0 }) }; window.addEventListener('hashchange', listener); return () => window.removeEventListener('hashchange', listener) }, [])
  useEffect(() => { const media = window.matchMedia('(max-width: 640px)'); const update = () => setIsMobile(media.matches); media.addEventListener('change', update); return () => media.removeEventListener('change', update) }, [])
  const current = navigation.find(item => item.id === route) ?? navigation[0]
  const status = error ? 'offline' : data?.state.anomaly ? data.state.anomaly.combined_status : data?.state.models.anomaly.available ? 'pending' : 'unavailable'
  const props = data ? { data, refresh, revision, offline: !!error } : null
  return <div className="app-shell">
    {mobileOpen && <button className="mobile-overlay" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
    <aside className={`sidebar ${mobileOpen ? 'mobile-open' : ''}`} inert={isMobile && !mobileOpen}>
      <a href="#overview" className="brand"><span className="brand-mark"><Leaf size={23} /></span><span>TraceX<span className="brand-sub">GREENGRID</span></span><span className="brand-dot" /></a>
      <div className="workspace-label">MONITORING WORKSPACE</div>
      <nav aria-label="Main navigation">{navigation.map(item => <a key={item.id} href={`#${item.id}`} className={`nav-link ${current.id === item.id ? 'active' : ''}`} aria-current={current.id === item.id ? 'page' : undefined}><item.icon size={18} /><span>{item.label}</span>{current.id === item.id && <ChevronRight size={14} />}</a>)}</nav>
      <div className="sidebar-bottom"><div className="simulation-note"><ShieldCheck size={19} /><div><strong>A safe space to investigate</strong><p>Software simulation only.<br />No physical devices connected.</p></div></div><a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer" className="api-link">API documentation<ArrowUpRight size={14} /></a><div className="sidebar-footer"><span className={`connection-dot ${error ? 'disconnected' : ''}`} />{error ? 'Backend disconnected' : data ? 'Local backend connected' : 'Connecting to backend'}<span>v0.6</span></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb"><button className="mobile-toggle icon-button" onClick={() => setMobileOpen(!mobileOpen)} aria-label="Toggle navigation">{mobileOpen ? <X size={20} /> : <Menu size={20} />}</button><span>GreenGrid</span><ChevronRight size={13} /><strong>{current.label}</strong></div><div className="topbar-right"><span className="simulation-tag">SIMULATION</span><span className="topbar-clock"><Activity size={14} />{data ? simTime(data.state.simulated_seconds) : '—'}</span><div className="avatar" title="Local workspace">TG</div></div></header>
      <main id="main-content">
        {error && <ErrorNotice>Connection interrupted. Displayed data is the last successful snapshot{updatedAt ? ` from ${new Date(updatedAt).toLocaleTimeString()}` : ''}. {error} <button className="inline-button" onClick={refresh}>Retry</button></ErrorNotice>}
        {data?.state.runtime_error && <ErrorNotice>The simulation stopped after a backend error: {data.state.runtime_error}. Reset the run before continuing.</ErrorNotice>}
        {!data ? <div className="initial-state"><Leaf size={35} /><h1>Connecting to GreenGrid</h1><p>The dashboard reads your local simulation at port 8000.</p>{error ? <p>Start FastAPI using the README command, then retry.</p> : <Loading />}</div> : <>
          <div className="context-strip"><span><i className={`status-dot ${status}`} /><span>{error ? 'Last known data' : data.state.running ? 'Simulation running' : 'Simulation paused'}</span><span className="context-divider" /><span>Seed {data.scenario.metadata.seed}</span><span className="context-divider" /><span>{data.state.config.solar_capacity_kw} kW microgrid</span></span><span>Run {data.state.run_id.slice(0, 8)} <Badge value={status}>{status === 'normal' ? 'No active anomaly' : status === 'pending' ? 'Awaiting first tick' : status === 'unavailable' ? 'Detector unavailable' : status}</Badge></span></div>
          <Suspense fallback={<Loading />}>{current.id === 'overview' && <Overview {...props!} />}{current.id === 'simulation' && <Simulation {...props!} />}{current.id === 'investigation' && <Investigation {...props!} />}{current.id === 'sustainability' && <Sustainability {...props!} />}{current.id === 'history' && <IncidentHistory {...props!} />}{current.id === 'evaluation' && <Evaluation {...props!} />}</Suspense>
          <footer className="page-footer"><span><Leaf size={13} />Built for a more resilient energy future.</span><span>Synthetic telemetry · {data.state.config.tick_seconds}s per tick · Local processing</span></footer>
        </>}
      </main>
    </div>
  </div>
}

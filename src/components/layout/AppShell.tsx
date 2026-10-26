import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, Bot, ChartNoAxesCombined, ChevronRight, CircleDot, LogOut, Menu, RadioTower, Zap } from 'lucide-react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../services/api'
import { getSeverity } from '../../utils/status'
import { useApiResource } from '../../hooks/useApiResource'
import { Badge } from '../ui'
import { ThemeToggle } from '../ui/ThemeToggle'
import { useAuth } from '../../context/AuthContext'

const routes = [
  { to: '/', label: 'System overview', icon: RadioTower, end: true },
  { to: '/simulation', label: 'Live simulation', icon: Activity },
  { to: '/investigation', label: 'Fault investigation', icon: AlertTriangle },
  { to: '/incidents', label: 'Incident history', icon: CircleDot },
  { to: '/evaluation', label: 'Model evaluation', icon: ChartNoAxesCombined },
]

const titles: Record<string, string> = {
  '/': 'System overview',
  '/simulation': 'Live simulation',
  '/investigation': 'Fault investigation',
  '/incidents': 'Incident history',
  '/evaluation': 'Model evaluation',
}

function timeLabel(value?: string | number, seconds?: number): string {
  if (typeof value === 'string' && value) return value
  const total = typeof value === 'number' ? value : seconds
  if (typeof total !== 'number' || !Number.isFinite(total)) return 'TIME UNKNOWN'
  const minute = Math.floor(total / 60)
  const h = Math.floor(minute / 60).toString().padStart(2, '0')
  const m = (minute % 60).toString().padStart(2, '0')
  return `${h}:${m}`
}

export function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [navOpen, setNavOpen] = useState(false)
  useEffect(() => setNavOpen(false), [location.pathname])
  const health = useApiResource('shell-health', api.getHealth, 15_000)
  const system = useApiResource('shell-state', api.getSystemState, 3_000)
  const currentTitle = titles[location.pathname] ?? 'System overview'
  const backendStatus = health.data?.backend
  const backendText = typeof backendStatus === 'string' ? backendStatus : backendStatus?.status ?? health.data?.status
  const modelStatus = typeof health.data?.model === 'string' ? health.data.model : health.data?.model?.status ?? health.data?.model_status
  const simStatus = system.data?.simulation_status ?? system.data?.status
  const anomalyStatus = system.data?.anomaly_status ?? system.data?.anomaly?.status

  return (
    <div className={`app-shell ${navOpen ? 'nav-open' : ''}`}>
      <aside className="sidebar">
        <NavLink className="brand" to="/" aria-label="Origin microgrid home">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span>Origin<small>GREEN GRID</small></span>
        </NavLink>
        <div className="workspace-switch"><span className="workspace-dot" /><span>Field lab<small>SIMULATION ENVIRONMENT</small></span><ChevronRight size={14} aria-hidden="true" /></div>
        <p className="side-label">WORKSPACE</p>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {routes.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
              <Icon size={16} aria-hidden="true" strokeWidth={1.7} />{label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection"><span className={`live-dot ${getSeverity(backendText) === 'normal' ? '' : 'muted-dot'}`} /><span>BACKEND {backendText?.toUpperCase() ?? 'UNKNOWN'}<small>API CONNECTION</small></span></div>
          <div className="side-foot">ORIGIN <span>MICROGRID / 01</span></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb"><span>Origin</span><b>/</b><strong>{currentTitle}</strong></div>
          <div className="topbar-right">
          <span className="simulation-clock"><Zap size={13} aria-hidden="true" />SIM TIME <strong>{timeLabel(system.data?.simulation_time, system.data?.simulation_time_seconds ?? system.data?.sim_time_seconds)}</strong></span>
            <Badge severity={getSeverity(simStatus)}>{simStatus?.toUpperCase() ?? 'STATUS UNKNOWN'}</Badge>
            <Badge severity={getSeverity(anomalyStatus)}><AlertTriangle size={12} aria-hidden="true" />ANOMALY {anomalyStatus?.toUpperCase() ?? 'UNKNOWN'}</Badge>
            <span className="health-chip" title="Model health"><Bot size={14} aria-hidden="true" /><span>MODEL</span><b>{modelStatus?.toUpperCase() ?? 'UNKNOWN'}</b></span>
            <button className="logout-button" onClick={() => { logout(); navigate('/welcome', { replace: true }) }} aria-label={`Sign out${user?.name ? `, ${user.name}` : ''}`}><LogOut size={14} aria-hidden="true" /><span>Sign out</span></button>
            <ThemeToggle />
            <button className="mobile-menu" aria-label="Toggle navigation" aria-expanded={navOpen} onClick={() => setNavOpen((open) => !open)}><Menu size={18} /></button>
          </div>
        </header>
        {health.error && <div className="global-warning" role="status">Backend health is unavailable. Data panels will show the API error state.</div>}
        <div className="page-content"><Outlet /></div>
        <footer className="footer-note"><span><b>ORIGIN / GREEN GRID</b> &nbsp;SIMULATED MICROGRID</span><span>SYNTHETIC SIGNALS · NOT FIELD MEASUREMENTS</span></footer>
      </main>
    </div>
  )
}

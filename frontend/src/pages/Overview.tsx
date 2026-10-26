import { lazy, Suspense } from 'react'
import { ArrowRight, BatteryCharging, Check, CircleAlert, Leaf, Play, Sun, Zap } from 'lucide-react'
import type { PageProps } from '../App'
import type { GraphData } from '../types'
import { useAction, useResource } from '../hooks/useData'
import { ActionFeedback, Badge, Empty, ErrorNotice, Loading, Metric, PageHeading, Panel, TextLink } from '../components/ui'
import { PowerChart } from '../components/Charts'
import { human, number, percent, sourceLabel } from '../utils/format'
const GridGraph = lazy(() => import('../components/GridGraph'))

export default function Overview({ data, refresh, offline }: PageProps) {
  const { state, sustainability, points, incidents, events } = data
  const row = state.telemetry
  const totals = sustainability.comparison.operated
  const action = useAction(refresh)
  const topology = useResource<GraphData>('/system/topology', 0, 0)
  const active = incidents.items.filter(item => item.status === 'open')
  return <>
    <PageHeading eyebrow="YOUR ENERGY, IN FOCUS" title="System overview" description="One connected view of generation, storage, and the signals in between." action={<a className="button primary" href="#simulation"><Play size={15} />Open simulation<ArrowRight size={15} /></a>} />
    <section className="overview-banner"><div className="banner-icon"><Leaf size={27} /></div><div><div className="eyebrow">RENEWABLE MICROGRID INTELLIGENCE</div><h2>A clearer view. A more resilient grid.</h2><p>Follow energy through your microgrid. Find disruptions before they become a bigger story.</p></div><div className="banner-status"><span className="muted">CURRENT DETECTION</span><Badge value={state.anomaly?.combined_status ?? 'unavailable'}>{state.anomaly ? state.anomaly.combined_status === 'normal' ? 'Within expected behavior' : 'Investigation recommended' : state.models.anomaly.available ? 'Awaiting first reading' : 'Detector unavailable'}</Badge></div></section>
    <div className="metric-grid">
      <Metric label="Solar generation" value={number(row?.actual_solar_kw)} unit="kW" icon={<Sun size={19} />} detail={`Rated capacity ${number(state.config.solar_capacity_kw, 0)} kW · actual simulated output`} />
      <Metric label="Battery charge" value={number(row?.battery_soc_pct, 1)} unit="%" icon={<BatteryCharging size={19} />} detail={row ? `${row.battery_power_kw < 0 ? 'Charging' : row.battery_power_kw > 0 ? 'Discharging' : 'Idle'} · ${number(Math.abs(row.battery_power_kw))} kW` : 'Awaiting first reading'} tone="cyan" />
      <Metric label="Energy delivered" value={number(row?.delivered_kw)} unit="kW" icon={<Zap size={19} />} detail={row ? `${number(row.demand_kw)} kW current demand` : 'Awaiting first reading'} tone="blue" />
      <Metric label="Renewable delivery" value={totals.ticks ? percent(totals.delivered_kwh ? totals.renewable_delivered_kwh / totals.delivered_kwh : null, 1) : '—'} icon={<Leaf size={19} />} detail="Renewable share of energy served this run" />
    </div>
    <div className="dashboard-two-col">
      <Panel title="Energy in motion" eyebrow="LIVE POWER FLOW" action={<span className="small-pill"><i className="status-dot normal" />Last {points.length} ticks</span>}><PowerChart points={points} /><div className="chart-footnote">Power in kW · Time in simulated minutes · Actual physical values</div></Panel>
      <Panel title="Grid at a glance" eyebrow="OPERATIONAL SNAPSHOT"><div className="health-stack">
        <div className="health-row"><span><CircleAlert size={17} />Active incidents</span><strong className={active.length ? 'text-amber' : 'text-green'}>{active.length}</strong></div>
        <div className="health-row"><span><Zap size={17} />Unmet demand</span><strong>{number(row?.unmet_demand_kw)} <small>kW</small></strong></div>
        <div className="health-row"><span><Sun size={17} />Solar reference</span><strong>{number(row?.expected_solar_kw)} <small>kW</small></strong></div>
        <div className="health-row"><span><BatteryCharging size={17} />Message age</span><strong>{number(row?.message_age_seconds, 0)} <small>s</small></strong></div>
      </div><div className="model-status"><div><span className={`status-dot ${state.models.anomaly.available ? 'normal' : 'unavailable'}`} />Anomaly detector <strong>{state.models.anomaly.available ? 'Available' : 'Unavailable'}</strong></div><div><span className={`status-dot ${state.models.source.available ? 'normal' : 'unavailable'}`} />Source classifier <strong>{state.models.source.available ? 'Available' : 'Unavailable'}</strong></div></div><p className="fine-print">ML scores and residual rules are reported separately. Predictions are hypotheses, not proven root causes.</p></Panel>
    </div>
    <div className="dashboard-two-col">
      <Panel title="A connected energy system" eyebrow="MICROGRID TOPOLOGY" action={<TextLink href="#investigation">Explore graph</TextLink>}>{topology.error ? <ErrorNotice>{topology.error}</ErrorNotice> : topology.data ? <Suspense fallback={<div className="graph-placeholder" />}><GridGraph graph={topology.data} compact /></Suspense> : <Loading>Loading component dependencies…</Loading>}<div className="chart-footnote">Documented information and physical dependencies. Incident-specific paths appear in investigation.</div></Panel>
      <Panel title="Recent activity" eyebrow="SYSTEM EVENT LOG" action={<span className="muted text-xs">This run</span>}><div className="event-list">{events.length ? [...events].reverse().slice(0, 6).map(event => <div className="event-item" key={event.id}><span className="event-icon"><Check size={13} /></span><div><strong>{human(event.event)}</strong><span>Tick {event.tick} · Software simulation</span></div><small>#{event.id}</small></div>) : <Empty title="No events yet" />}</div></Panel>
    </div>
    {!!active.length && <Panel title="Open investigations" action={<TextLink href="#history">View all incidents</TextLink>}><div className="incident-cards">{active.slice(0, 3).map(incident => <a key={incident.id} className="incident-card" href={`#investigation?id=${encodeURIComponent(incident.id)}`}><Badge value={incident.severity} /><strong>{sourceLabel(incident.diagnosis.source)}</strong><span>Detected at tick {incident.detection_tick}</span><ArrowRight size={16} /></a>)}</div></Panel>}
    {!state.next_tick && <div className="notice"><Play size={16} /><span>Ready when you are. Start a healthy run or advance 20 ticks to populate the dashboard.</span><button className="button small" disabled={action.busy || offline} onClick={() => action.act('/simulation/step', { ticks: 20 }, 'Advanced 20 simulation ticks')}>Advance 20 ticks</button></div>}
    <ActionFeedback error={action.error} message={action.message} />
  </>
}

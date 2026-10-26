import { useApiResource } from '../hooks/useApiResource'
import { useLiveTelemetry } from '../hooks/useLiveTelemetry'
import { api } from '../services/api'
import type { EventRecord, TopologyResponse } from '../types/domain'
import { normalizeTelemetry, readMetric } from '../utils/data'
import { TimeSeriesChart } from '../components/charts/TimeSeriesChart'
import { DependencyGraph } from '../components/system/DependencyGraph'
import { Badge, Button, Card, EmptyState, Stat } from '../components/ui'
import { getSeverity, simulationLabel } from '../utils/status'

export function OverviewPage() {
  const system = useApiResource('overview-system', api.getSystemState, 5_000)
  const topology = useApiResource<TopologyResponse>('overview-topology', api.getTopology)
  const events = useApiResource<EventRecord[]>(`overview-events-${system.data?.run_id ?? 'active'}`, () => api.getEvents(8, system.data?.run_id), 10_000, !!system.data?.run_id)
  const { points, stream, error: telemetryError } = useLiveTelemetry()
  const metrics = system.data?.metrics
  const activeCount = readMetric(metrics, 'active_incidents') ?? system.data?.active_incidents
  const normalized = normalizeTelemetry(points)

  return (
    <>
      <div className="page-intro">
        <div><p className="eyebrow">MICROGRID / SYSTEM STATUS</p><h1>System overview</h1><p className="intro-copy">Operating signals and fault indicators from the current simulation.</p></div>
        <div className="intro-actions"><Badge severity={getSeverity(system.data?.anomaly_status ?? system.data?.anomaly?.status)}>{system.data?.anomaly_status ? `ANOMALY ${simulationLabel(system.data.anomaly_status)}` : 'ANOMALY UNKNOWN'}</Badge><span className="stream-label">{stream === 'polling' ? 'POLLING' : 'STREAM UNKNOWN'}</span></div>
      </div>
      {system.loading && !system.data && <EmptyState title="Loading microgrid state" detail="Waiting for current simulation health and metrics." kind="loading" />}
      {system.error && <EmptyState title="System state unavailable" detail={system.error} kind="error" action={<Button variant="secondary" onClick={system.reload}>Retry</Button>} />}
      <div className="stat-grid seven-stats">
        <Stat label="Solar generation" value={readMetric(metrics, metrics?.solar_generation_kw !== undefined ? 'solar_generation_kw' : 'solar_generation_kwh')} unit={metrics?.solar_generation_kw !== undefined ? 'kW' : metrics?.solar_generation_kwh !== undefined ? 'kWh' : undefined} severity="normal" />
        <Stat label="Battery SoC" value={readMetric(metrics, 'battery_soc_pct')} unit="%" />
        <Stat label="Demand" value={readMetric(metrics, 'demand_kw')} unit="kW" />
        <Stat label="Energy delivered" value={readMetric(metrics, 'energy_delivered_kwh')} unit="kWh" severity="normal" />
        <Stat label="Renewable utilization" value={readMetric(metrics, 'renewable_utilization_pct')} unit="%" severity="normal" />
        <Stat label="Unmet demand" value={readMetric(metrics, 'unmet_demand_kwh')} unit="kWh" severity={readMetric(metrics, 'unmet_demand_kwh') === undefined ? 'unknown' : readMetric(metrics, 'unmet_demand_kwh')! > 0 ? 'warning' : 'normal'} />
        <Stat label="Active incidents" value={activeCount} note={activeCount === undefined ? 'Not reported by API' : 'Current incident count'} severity={activeCount === undefined ? 'unknown' : activeCount > 0 ? 'critical' : 'normal'} />
      </div>

      <div className="two-column-grid overview-charts">
        <Card title="Power balance" eyebrow="TELEMETRY / POWER" action={<span className="micro-label">kW · SIMULATED</span>}>
          {telemetryError && !normalized.length ? <EmptyState title="Telemetry unavailable" detail={telemetryError} kind="error" /> : <TimeSeriesChart data={normalized} unit="kW" series={[{ key: 'solar_generation_kw', label: 'Solar', color: 'var(--chart-solar)' }, { key: 'demand_kw', label: 'Demand', color: 'var(--chart-demand)' }, { key: 'delivered_kw', label: 'Delivered', color: 'var(--chart-delivered)' }]} />}
        </Card>
        <Card title="Storage and anomaly signal" eyebrow="TELEMETRY / STATE" action={<span className="micro-label">API VALUES ONLY</span>}>
          {telemetryError && !normalized.length ? <EmptyState title="Telemetry unavailable" detail={telemetryError} kind="error" /> : <TimeSeriesChart data={normalized} unit="%" series={[{ key: 'battery_soc_pct', label: 'Battery SoC', color: 'var(--chart-delivered)', unit: '%', axis: 'left' }, { key: 'anomaly_score', label: 'Model anomaly score', color: 'var(--chart-anomaly)', unit: 'score', axis: 'right' }]} />}
        </Card>
      </div>

      <div className="two-column-grid overview-bottom">
        <Card title="Microgrid components" eyebrow="TOPOLOGY / DEPENDENCIES" action={topology.data && <span className="micro-label">{topology.data.nodes.length} COMPONENTS</span>}>
          {topology.loading && !topology.data ? <EmptyState title="Loading topology" kind="loading" /> : topology.error ? <EmptyState title="Topology unavailable" detail={topology.error} kind="error" action={<Button onClick={topology.reload}>Retry</Button>} /> : topology.data?.nodes.length ? <><DependencyGraph nodes={topology.data.nodes} edges={topology.data.edges} height={390} /><p className="graph-note">Solid links show known dependencies. Dashed amber links mark suspected propagation paths.</p></> : <EmptyState title="No topology data" detail="The topology endpoint returned no components." kind="unknown" />}
        </Card>
        <Card title="Recent events" eyebrow="EVENT STREAM" action={<span className="micro-label">{events.data?.length ?? '—'} EVENTS</span>}>
          {events.loading && !events.data ? <EmptyState title="Loading recent events" kind="loading" /> : events.error ? <EmptyState title="Events unavailable" detail={events.error} kind="error" action={<Button onClick={events.reload}>Retry</Button>} /> : events.data?.length ? <EventList events={events.data} /> : <EmptyState title="No recent events" detail="No events were returned for the current simulation." />}
        </Card>
      </div>
      <div className="data-footnote">Health, telemetry and incident values come from the API. A dash means the backend did not return that metric.</div>
    </>
  )
}

function EventList({ events }: { events: EventRecord[] }) {
  return <div className="event-list">{events.map((event, index) => {
    const eventName = (event.event ?? event.type ?? 'event').toLowerCase()
    const labels: Record<string, string> = {
      scenario_created: 'Simulation scenario created', simulation_started: 'Simulation started',
      simulation_paused: 'Simulation paused', simulation_resumed: 'Simulation resumed',
      simulation_reset: 'Simulation reset', scenario_transition: 'Scenario changed',
      incident_opened: 'Anomaly detected · incident opened', incident_resolved: 'Incident resolved',
      fault_injected: 'Simulated fault injected', attack_injected: 'Simulated attack scheduled',
    }
    const title = event.message ?? event.description ?? labels[eventName] ?? eventName.replaceAll('_', ' ')
    const severity = getSeverity(event.severity)
    return <div className="event-row" key={event.id ?? `${event.timestamp ?? event.time}-${index}`}><span className={`event-marker marker-${severity}`} aria-hidden="true" /><div className="event-copy"><strong>{title}</strong><small>{event.timestamp ?? event.time ?? (event.tick !== undefined ? `Tick ${event.tick}` : 'Time unavailable')}</small></div><Badge severity={severity}>{event.severity?.toUpperCase() ?? 'EVENT'}</Badge></div>
  })}</div>
}

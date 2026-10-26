import { useApiResource } from '../hooks/useApiResource'
import { api } from '../services/api'
import type { SustainabilityResponse } from '../types/domain'
import { formatNumber } from '../utils/data'
import { Badge, Button, Card, EmptyState, Stat } from '../components/ui'

const fields = [
  ['generated_kwh', 'Generated energy', 'kWh', false],
  ['delivered_kwh', 'Delivered energy', 'kWh', false],
  ['curtailed_kwh', 'Curtailed energy', 'kWh', false],
  ['demand_served_pct', 'Demand served', '%', false],
  ['unmet_demand_kwh', 'Unmet demand', 'kWh', false],
  ['battery_efficiency_pct', 'Battery efficiency', '%', false],
  ['estimated_loss_kwh', 'Estimated loss', 'kWh', true],
] as const

function metricValue(data: SustainabilityResponse, key: string): { value?: number | null; estimated: boolean } {
  const direct = data[key as keyof SustainabilityResponse]
  if (typeof direct === 'number' || direct === null) return { value: direct, estimated: key === 'estimated_loss_kwh' }
  const metric = data.metrics?.[key]
  if (typeof metric === 'number' || metric === null) return { value: metric, estimated: false }
  if (metric && typeof metric === 'object') return { value: metric.value, estimated: !!metric.estimated }
  return { value: undefined, estimated: key === 'estimated_loss_kwh' }
}

export function SustainabilityPage() {
  const resource = useApiResource('sustainability', api.getSustainability, 15_000)
  const data = resource.data
  const comparison = data?.comparison
  const comparisonRows = comparison ? [...new Set([
    ...Object.keys(comparison.normal ?? {}),
    ...Object.keys(comparison.faulty ?? {}),
    ...Object.keys(comparison.after_correction ?? {}),
  ])] : []

  return <>
    <div className="page-intro"><div><p className="eyebrow">ENERGY / PERFORMANCE</p><h1>Sustainability</h1><p className="intro-copy">Energy outcomes from the current simulated run, with estimates marked explicitly.</p></div><Badge severity="unknown">{data ? 'API VALUES' : 'DATA UNKNOWN'}</Badge></div>
    {resource.loading && !data && <EmptyState title="Loading sustainability metrics" kind="loading" />}
    {resource.error && <EmptyState title="Sustainability data unavailable" detail={resource.error} kind="error" action={<Button onClick={resource.reload}>Retry</Button>} />}
    {!resource.loading && !resource.error && !data && <EmptyState title="No sustainability data" detail="The metrics endpoint returned no response." kind="unknown" />}
    {data && <>
      <div className="stat-grid sustainability-stats">{fields.map(([key, label, unit, estimate]) => {
        const metric = metricValue(data, key)
        return <Stat key={key} label={label} value={metric.value} unit={unit} estimate={estimate || metric.estimated} severity={key === 'unmet_demand_kwh' && metric.value && metric.value > 0 ? 'warning' : 'unknown'} />
      })}</div>
      <div className="two-column-grid sustainability-lower">
        <Card title="Scenario comparison" eyebrow="NORMAL / FAULTY / AFTER CORRECTION">
          {comparisonRows.length ? <div className="table-scroll"><table className="data-table comparison-table"><thead><tr><th>Metric</th><th>Normal</th><th>Faulty</th><th>After correction</th></tr></thead><tbody>{comparisonRows.map((key) => <tr key={key}><th>{key.replaceAll('_', ' ')}</th><td>{displayComparison(comparison?.normal?.[key])}</td><td>{displayComparison(comparison?.faulty?.[key])}</td><td>{displayComparison(comparison?.after_correction?.[key])}</td></tr>)}</tbody></table></div> : <EmptyState title="Comparison unavailable" detail="The API did not provide normal, faulty, and after-correction values." kind="unknown" />}
        </Card>
        <Card title="Assumptions and labels" eyebrow="HOW TO READ THESE VALUES">
          <p className="intro-copy">Directly simulated quantities are reported as returned by the backend. Estimated values are identified with <span className="estimate-tag">EST.</span> No missing values are inferred.</p>
          {data.assumptions?.length ? <ul className="assumption-list">{data.assumptions.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <EmptyState title="No assumptions provided" detail="The API response did not include calculation assumptions." kind="unknown" />}
        </Card>
      </div>
    </>}
  </>
}

function displayComparison(value: number | null | undefined) {
  return value === null || value === undefined ? '—' : formatNumber(value, 2)
}


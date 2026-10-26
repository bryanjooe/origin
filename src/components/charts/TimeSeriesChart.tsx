import { useMemo } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { TelemetryPoint } from '../../types/domain'
import { EmptyState } from '../ui'

export interface ChartSeries {
  key: keyof TelemetryPoint | string
  label: string
  color: string
  axis?: 'left' | 'right'
  unit?: string
}

export function TimeSeriesChart({
  data,
  series,
  unit,
  height = 240,
}: {
  data: TelemetryPoint[]
  series: ChartSeries[]
  unit: string
  height?: number
}) {
  const chartData = useMemo(() => data.slice(-360).map((point, index) => ({
    ...point,
    __index: index,
    __time: point.timestamp ?? point.time ?? (typeof point.simulation_time === 'string' ? point.simulation_time : `${point.tick ?? index}`),
  })), [data])

  if (!chartData.length) return <EmptyState title="Telemetry unavailable" detail="Waiting for telemetry from the simulation API." kind="unknown" />
  const available = series.filter((item) => chartData.some((row) => {
    const value = (row as TelemetryPoint)[item.key]
    return typeof value === 'number' && Number.isFinite(value)
  }))
  if (!available.length) return <EmptyState title="No chartable series" detail="The telemetry response does not include these fields." kind="unknown" />

  return (
    <div className="chart-container" style={{ height }} role="img" aria-label={`Time series chart showing ${available.map((item) => `${item.label} (${item.unit ?? unit})`).join(', ')}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 5" vertical={false} />
          <XAxis dataKey="__time" minTickGap={36} tick={{ fill: 'var(--chart-label)', fontSize: 9, fontFamily: 'var(--mono)' }} axisLine={{ stroke: 'var(--chart-axis)' }} tickLine={false} />
          <YAxis yAxisId="left" unit={` ${available.find((item) => (item.axis ?? 'left') === 'left')?.unit ?? unit}`} width={62} tick={{ fill: 'var(--chart-label)', fontSize: 9, fontFamily: 'var(--mono)' }} axisLine={false} tickLine={false} />
          {available.some((item) => item.axis === 'right') && <YAxis yAxisId="right" orientation="right" unit={` ${available.find((item) => item.axis === 'right')?.unit ?? ''}`} width={58} tick={{ fill: 'var(--chart-label)', fontSize: 9, fontFamily: 'var(--mono)' }} axisLine={false} tickLine={false} />}
          <Tooltip formatter={(value, name) => { const item = available.find((seriesItem) => seriesItem.label === String(name)); const formatted = typeof value === 'number' ? value.toFixed(2) : String(value ?? '—'); return [`${formatted} ${item?.unit ?? unit}`, String(name)] }} contentStyle={{ background: 'var(--paper-bright)', border: '1px solid var(--line-strong)', borderRadius: 0, color: 'var(--ink)', fontSize: 10 }} labelStyle={{ fontFamily: 'var(--mono)' }} />
          <Legend verticalAlign="top" align="right" height={30} iconType="plainline" wrapperStyle={{ color: 'var(--muted)', fontSize: 9 }} />
          {available.map((item) => <Line key={item.key} yAxisId={item.axis ?? 'left'} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={1.8} dot={false} activeDot={{ r: 3 }} isAnimationActive={false} connectNulls={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, BarChart, Bar } from 'recharts'
import type { TelemetryPoint } from '../types'
import { Empty } from './ui'
import { number } from '../utils/format'

const tooltip = { background: '#111c2b', border: '1px solid #2a3a50', borderRadius: 10, color: '#e7edf6', fontSize: 12 }
const axis = { fill: '#8090a6', fontSize: 11 }
export function PowerChart({ points, detailed = false }: { points: TelemetryPoint[]; detailed?: boolean }) {
  if (!points.length) return <Empty title="Waiting for the first tick">Start the simulation or advance a few ticks to build a live trace.</Empty>
  const rows = points.map(({ telemetry: row }) => ({ ...row, time: row.elapsed_seconds / 60 }))
  return <div className="chart" role="img" aria-label="Time series of solar generation, demand, delivery, and battery power"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={rows} margin={{ top: 12, right: 10, left: -12, bottom: 8 }}>
    <defs><linearGradient id="solarFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#4fe0a2" stopOpacity={0.14} /><stop offset="100%" stopColor="#4fe0a2" stopOpacity={0} /></linearGradient></defs>
    <CartesianGrid stroke="#202d3e" strokeDasharray="3 5" vertical={false} />
    <XAxis dataKey="time" tick={axis} axisLine={false} tickLine={false} minTickGap={45} tickFormatter={value => `${number(value, 0)}m`} />
    <YAxis tick={axis} axisLine={false} tickLine={false} unit=" kW" width={60} />
    <Tooltip contentStyle={tooltip} labelFormatter={value => `${number(Number(value), 1)} simulated minutes`} formatter={value => `${number(Number(value), 3)} kW`} />
    <Legend iconType="plainline" wrapperStyle={{ fontSize: 11, paddingTop: 16 }} />
    <Area name="Actual solar" dataKey="actual_solar_kw" stroke="#4fe0a2" fill="url(#solarFill)" strokeWidth={2} isAnimationActive={false} />
    <Line name="Demand" dataKey="demand_kw" stroke="#8d9bb1" strokeDasharray="5 4" dot={false} strokeWidth={1.5} isAnimationActive={false} />
    <Line name="Delivered" dataKey="delivered_kw" stroke="#5dcbef" dot={false} strokeWidth={2} isAnimationActive={false} />
    {detailed && <Line name="Sensor-reported solar" dataKey="measured_solar_kw" stroke="#b798f5" dot={false} strokeWidth={1.5} isAnimationActive={false} />}
    {detailed && <Line name="Battery (+ discharge)" dataKey="battery_power_kw" stroke="#f3b76a" dot={false} strokeWidth={1.5} isAnimationActive={false} />}
  </ComposedChart></ResponsiveContainer></div>
}
export function BatteryChart({ points }: { points: TelemetryPoint[] }) {
  return <div className="chart chart-small" role="img" aria-label="Battery state of charge over simulated time"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={points.map(p => p.telemetry)} margin={{ left: -16, right: 12 }}>
    <CartesianGrid stroke="#202d3e" strokeDasharray="3 5" vertical={false} />
    <XAxis dataKey="tick" tick={axis} minTickGap={35} axisLine={false} tickLine={false} /><YAxis domain={[0, 100]} tick={axis} unit="%" axisLine={false} tickLine={false} />
    <Tooltip contentStyle={tooltip} labelFormatter={value => `Tick ${value}`} formatter={value => `${number(Number(value))}%`} />
    <Line dataKey="battery_soc_pct" name="Physical SOC" stroke="#4fe0a2" strokeWidth={2} dot={false} isAnimationActive={false} />
    <Line dataKey="measured_soc_pct" name="Sensor SOC" stroke="#b798f5" strokeWidth={1.5} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
  </ComposedChart></ResponsiveContainer></div>
}
export function EnergyComparison({ data }: { data: { name: string; delivered: number; unmet: number }[] }) {
  return <div className="chart" role="img" aria-label="Baseline, faulty, and corrected demand delivery comparison"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} barGap={8} margin={{ left: -12, right: 10 }}>
    <CartesianGrid stroke="#202d3e" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="name" tick={axis} axisLine={false} tickLine={false} /><YAxis tick={axis} unit=" kWh" axisLine={false} tickLine={false} width={65} />
    <Tooltip contentStyle={tooltip} formatter={value => `${number(Number(value), 3)} kWh`} /><Legend wrapperStyle={{ fontSize: 11 }} />
    <Bar name="Demand served" dataKey="delivered" fill="#4fe0a2" radius={[4, 4, 0, 0]} maxBarSize={58} /><Bar name="Unmet demand" dataKey="unmet" fill="#f3b76a" radius={[4, 4, 0, 0]} maxBarSize={58} />
  </BarChart></ResponsiveContainer></div>
}

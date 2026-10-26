import type { ReactNode } from 'react'
import { AlertCircle, CheckCircle2, CircleHelp, Info, LoaderCircle, Play, Pause, Square } from 'lucide-react'
import type { Severity } from '../types/domain'

export function Card({
  title,
  eyebrow,
  action,
  children,
  className = '',
}: {
  title?: string
  eyebrow?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || eyebrow || action) && (
        <header className="panel-heading">
          <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}{title && <h2>{title}</h2>}</div>
          {action && <div className="panel-action">{action}</div>}
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  )
}

export function Badge({ severity, children, status }: { severity: Severity; children: ReactNode; status?: string }) {
  const state = status?.toLowerCase()
  const Icon = state === 'running' ? Play : state === 'paused' ? Pause : state === 'stopped' || state === 'idle' ? Square
    : severity === 'normal' ? CheckCircle2 : severity === 'warning' || severity === 'critical' ? AlertCircle : Info
  return <span className={`badge badge-${severity}`}><Icon aria-hidden="true" size={13} strokeWidth={1.8} />{children}</span>
}

export function Button({
  children,
  variant = 'secondary',
  icon,
  disabled,
  loading,
  type = 'button',
  onClick,
  className = '',
  title,
}: {
  children: ReactNode
  variant?: 'primary' | 'secondary' | 'danger' | 'quiet'
  icon?: ReactNode
  disabled?: boolean
  loading?: boolean
  type?: 'button' | 'submit'
  onClick?: () => void
  className?: string
  title?: string
}) {
  return (
    <button type={type} title={title} className={`button button-${variant} ${className}`} disabled={disabled || loading} onClick={onClick}>
      {loading ? <LoaderCircle aria-hidden="true" size={15} className="spin" /> : icon}
      {children}
    </button>
  )
}

export function Stat({
  label,
  value,
  unit,
  note,
  severity = 'unknown',
  estimate = false,
}: {
  label: string
  value: string | number | null | undefined
  unit?: string
  note?: string
  severity?: Severity
  estimate?: boolean
}) {
  const shown = value === null || value === undefined || value === '' || (typeof value === 'number' && !Number.isFinite(value)) ? '—' : typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value
  return (
    <article className={`stat-card stat-${severity}`}>
      <div className="stat-label">{label}{estimate && <span className="estimate-tag">EST.</span>}</div>
      <div className="stat-value"><strong>{shown}</strong>{unit && <span>{unit}</span>}</div>
      {note && <div className="stat-note">{note}</div>}
    </article>
  )
}

export function EmptyState({
  title,
  detail,
  kind = 'empty',
  action,
}: {
  title: string
  detail?: string
  kind?: 'empty' | 'error' | 'loading' | 'unknown'
  action?: ReactNode
}) {
  const Icon = kind === 'error' ? AlertCircle : kind === 'loading' ? LoaderCircle : kind === 'unknown' ? CircleHelp : Info
  return (
    <div className={`empty-state empty-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <Icon size={18} aria-hidden="true" className={kind === 'loading' ? 'spin' : ''} />
      <strong>{title}</strong>
      {detail && <p>{detail}</p>}
      {action}
    </div>
  )
}

export interface TableColumn<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  className?: string
}

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  onRowClick,
  empty,
}: {
  rows: T[]
  columns: TableColumn<T>[]
  rowKey: (row: T) => string | number
  onRowClick?: (row: T) => void
  empty?: ReactNode
}) {
  if (rows.length === 0) return <>{empty ?? <EmptyState title="No records found" detail="Try changing the filters or refresh the data." />}</>
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr>{columns.map((column) => <th key={column.key} className={column.className}>{column.header}</th>)}</tr></thead>
        <tbody>{rows.map((row) => (
          <tr key={rowKey(row)} onClick={onRowClick ? () => onRowClick(row) : undefined} tabIndex={onRowClick ? 0 : undefined} onKeyDown={onRowClick ? (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onRowClick(row) } } : undefined}>
            {columns.map((column) => <td key={column.key} className={column.className}>{column.render(row)}</td>)}
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

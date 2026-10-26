import type { ReactNode } from 'react'
import { ArrowUpRight, CircleAlert, LoaderCircle } from 'lucide-react'
import { human } from '../utils/format'

export function Badge({ value, children }: { value: string; children?: ReactNode }) { return <span className={`badge badge-${value}`}><i />{children ?? human(value)}</span> }
export function Panel({ title, eyebrow, action, children, className = '' }: { title?: string; eyebrow?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{(title || action) && <div className="panel-heading"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2></div>{action}</div>}{children}</section>
}
export function Metric({ label, value, unit, icon, detail, tone = 'green' }: { label: string; value: ReactNode; unit?: string; icon: ReactNode; detail?: ReactNode; tone?: string }) {
  return <div className={`metric metric-${tone}`}><div className="metric-top"><span>{label}</span><span className="metric-icon">{icon}</span></div><div className="metric-number">{value}<small>{unit}</small></div><div className="metric-detail">{detail ?? 'Current simulation reading'}</div></div>
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty"><div className="empty-icon"><CircleAlert size={22} /></div><h3>{title}</h3>{children && <p>{children}</p>}</div> }
export function Loading({ children = 'Reading simulation data…' }: { children?: ReactNode }) { return <div className="loading"><LoaderCircle size={20} className="spin" />{children}</div> }
export function ErrorNotice({ children }: { children: ReactNode }) { return <div className="notice error" role="alert"><CircleAlert size={17} /><span>{children}</span></div> }
export function ActionFeedback({ error, message }: { error: string | null; message: string | null }) { return <>{error && <ErrorNotice>{error}</ErrorNotice>}{message && <div className="notice success" role="status">{message}</div>}</> }
export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action && <div className="heading-action">{action}</div>}</div>
}
export function TextLink({ children, href }: { children: ReactNode; href: string }) { return <a className="text-link" href={href}>{children}<ArrowUpRight size={14} /></a> }

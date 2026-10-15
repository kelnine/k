import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

export function Card({
  title,
  actions,
  children,
  className = '',
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function Stat({
  label,
  value,
  sub,
  tone = '',
  title,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: string
  title?: string
}) {
  return (
    <div className="stat" title={title}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone}`}>{value}</div>
      {sub !== undefined && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'muted'

export function Badge({ tone = 'muted', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge ${tone}`} title={title}>
      {children}
    </span>
  )
}

const STATE_TONES: Record<string, Tone> = {
  RUNNING: 'ok',
  LIVE: 'ok',
  ACTIVE: 'ok',
  OK: 'ok',
  COMPLETED: 'info',
  APPROVED: 'ok',
  STARTING: 'info',
  WARMING_UP: 'info',
  CATCHING_UP: 'warn',
  STALE: 'warn',
  CLOSED: 'muted',
  NO_PROVIDER: 'bad',
  DELAYED: 'warn',
  PAUSED: 'warn',
  HALTED: 'bad',
  STOPPED: 'muted',
  QUEUED: 'muted',
  FAULTED: 'bad',
  FAILED: 'bad',
  ERROR: 'bad',
  DISCONNECTED: 'bad',
  REJECTED: 'bad',
  INVALID: 'bad',
  BREACHED: 'bad',
  LOCKED_FOR_DAY: 'warn',
  IGNORED: 'muted',
  NO_DECISION: 'muted',
  CANCELLED: 'muted',
}

export function stateTone(state: string | null | undefined): Tone {
  return (state && STATE_TONES[state.toUpperCase()]) || 'muted'
}

export function StateBadge({ state, title }: { state: string | null | undefined; title?: string }) {
  return (
    <Badge tone={stateTone(state)} title={title}>
      {state ? state.replace(/_/g, ' ').toLowerCase() : 'unknown'}
    </Badge>
  )
}

export function Dot({ tone }: { tone: Tone }) {
  return <span className={`dot ${tone}`} aria-hidden="true" />
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-title">{title}</div>
      {children && <div className="empty-body">{children}</div>}
    </div>
  )
}

export function ErrorBox({ error }: { error: Error | null }) {
  if (!error) return null
  const text = error instanceof ApiError && error.status === 0 ? 'The API cannot be reached.' : error.message
  return <div className="error-box">⚠ {text}</div>
}

export function Loading() {
  return <div className="loading">Loading…</div>
}

export function Pager({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
}) {
  if (total <= limit) return total > 0 ? <div className="pager muted">{total} rows</div> : null
  const last = Math.max(0, Math.floor((total - 1) / limit) * limit)
  return (
    <div className="pager">
      <button className="btn small" disabled={offset === 0} onClick={() => onChange(0)}>
        «
      </button>
      <button className="btn small" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        ‹ Prev
      </button>
      <span className="muted">
        {offset + 1}–{Math.min(total, offset + limit)} of {total}
      </span>
      <button className="btn small" disabled={offset >= last} onClick={() => onChange(offset + limit)}>
        Next ›
      </button>
      <button className="btn small" disabled={offset >= last} onClick={() => onChange(last)}>
        »
      </button>
    </div>
  )
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode }[]
  value: T
  onChange: (id: T) => void
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={tab.id === value}
          className={`tab ${tab.id === value ? 'on' : ''}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export function Select({
  label,
  value,
  options,
  onChange,
  allLabel = 'All',
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
  allLabel?: string | null
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {allLabel !== null && <option value="">{allLabel}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Json({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>
}

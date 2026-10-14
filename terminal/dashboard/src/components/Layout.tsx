import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { RuntimeView } from '../api/types'
import { useAuth } from '../auth'
import { ago } from '../lib/format'
import { useNow, usePoll } from '../lib/hooks'
import { Link, useLocation } from '../lib/router'
import { Dot, type Tone } from './ui'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/instruments', label: 'Instruments' },
  { to: '/chart', label: 'Chart' },
  { to: '/trades', label: 'Trades' },
  { to: '/signals', label: 'Signals' },
  { to: '/system', label: 'System' },
]

interface SystemInfo {
  version: string
  environment: string
  default_mode: string
  live_trading_permitted: boolean
}

export function runtimeTone(view: RuntimeView | null): Tone {
  if (!view || !view.present) return 'muted'
  if (view.stale || view.error) return 'bad'
  const status = view.status?.status?.toUpperCase()
  if (status === 'RUNNING') return 'ok'
  if (status === 'FAILED' || status === 'FAULTED') return 'bad'
  return 'warn'
}

export function runtimeLabel(view: RuntimeView | null): string {
  if (!view) return 'runtime …'
  if (!view.present) return 'no forward session'
  if (view.error) return 'status unreadable'
  if (view.stale) return 'runtime silent'
  return (view.status?.status ?? 'unknown').toLowerCase()
}

export function Layout({ children }: { children: ReactNode }) {
  const { session, signOut } = useAuth()
  const { path } = useLocation()
  const now = useNow(5000)
  const runtime = usePoll(() => api.get<RuntimeView>('/system/runtime'), [])
  const [info, setInfo] = useState<SystemInfo | null>(null)

  useEffect(() => {
    api.get<SystemInfo>('/system/info').then(setInfo, () => setInfo(null))
  }, [])

  const active = (to: string) => (to === '/' ? path === '/' || path.startsWith('/accounts') : path.startsWith(to))
  const view = runtime.data
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          K<span className="brand-dot">·</span>Terminal
        </Link>
        <nav className="nav">
          {NAV.map((item) => (
            <Link key={item.to} to={item.to} className={`nav-link ${active(item.to) ? 'on' : ''}`}>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="spacer" />
        <div
          className="pill"
          title={view?.status?.updated_at ? `last update ${ago(view.status.updated_at, now)}` : undefined}
        >
          <Dot tone={runtimeTone(view)} /> {runtimeLabel(view)}
        </div>
        {info && (
          <div className="pill mode" title={`environment ${info.environment} · v${info.version}`}>
            {info.default_mode} · live {info.live_trading_permitted ? 'ENABLED' : 'off'}
          </div>
        )}
        {session && (
          <div className="user">
            <span className="user-name">{session.user.username}</span>
            <span className="user-role">{session.user.role.toLowerCase()}</span>
            <button className="btn small ghost" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        )}
      </header>
      <main className="main">{children}</main>
    </div>
  )
}

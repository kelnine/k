// A minimal history router: the dashboard has a handful of pages, so a dependency is
// not worth it. Caddy (and vite preview) answer every unknown path with index.html.

import { useEffect, useState, type MouseEvent, type ReactNode } from 'react'

const listeners = new Set<() => void>()

function notify(): void {
  for (const listener of listeners) listener()
}

window.addEventListener('popstate', notify)

export function navigate(to: string, { replace = false }: { replace?: boolean } = {}): void {
  if (to === window.location.pathname + window.location.search) return
  if (replace) window.history.replaceState(null, '', to)
  else window.history.pushState(null, '', to)
  window.scrollTo(0, 0)
  notify()
}

/** Replace query parameters of the current page (filters), keeping the path. */
export function setQuery(updates: Record<string, string | null | undefined>): void {
  const search = new URLSearchParams(window.location.search)
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === undefined || value === '') search.delete(key)
    else search.set(key, value)
  }
  const text = search.toString()
  window.history.replaceState(null, '', `${window.location.pathname}${text ? `?${text}` : ''}`)
  notify()
}

export interface Location {
  path: string
  query: URLSearchParams
}

export function useLocation(): Location {
  const [, setTick] = useState(0)
  useEffect(() => {
    const listener = () => setTick((n) => n + 1)
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }, [])
  return { path: window.location.pathname, query: new URLSearchParams(window.location.search) }
}

/** `match('/accounts/:id', '/accounts/42')` → `{ id: '42' }`, or null. */
export function match(pattern: string, path: string): Record<string, string> | null {
  const a = pattern.split('/').filter(Boolean)
  const b = path.split('/').filter(Boolean)
  if (a.length !== b.length) return null
  const out: Record<string, string> = {}
  for (let i = 0; i < a.length; i++) {
    if (a[i].startsWith(':')) out[a[i].slice(1)] = decodeURIComponent(b[i])
    else if (a[i] !== b[i]) return null
  }
  return out
}

export function Link({
  to,
  children,
  className,
  title,
}: {
  to: string
  children: ReactNode
  className?: string
  title?: string
}) {
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return
    event.preventDefault()
    navigate(to)
  }
  return (
    <a href={to} onClick={onClick} className={className} title={title}>
      {children}
    </a>
  )
}

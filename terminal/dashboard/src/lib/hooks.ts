import { useCallback, useEffect, useRef, useState } from 'react'

export const POLL_MS = 10_000

export interface Poll<T> {
  data: T | null
  error: Error | null
  loading: boolean
  updatedAt: number | null
  refresh: () => void
}

/**
 * Fetch now and every `intervalMs` (10 s) while the tab is visible; refetch at once
 * when it becomes visible again. The last good data stays on screen while a refresh
 * is in flight or fails. Responses that arrive after a newer request started are
 * dropped, so changing filters never shows stale results.
 */
export function usePoll<T>(fetcher: () => Promise<T>, deps: unknown[], intervalMs = POLL_MS): Poll<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const generation = useRef(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const run = useCallback(() => {
    const mine = ++generation.current
    setLoading(true)
    fetcherRef
      .current()
      .then((result) => {
        if (mine !== generation.current) return
        setData(result)
        setError(null)
        setUpdatedAt(Date.now())
      })
      .catch((err: unknown) => {
        if (mine !== generation.current) return
        setError(err instanceof Error ? err : new Error(String(err)))
      })
      .finally(() => {
        if (mine === generation.current) setLoading(false)
      })
  }, [])

  useEffect(() => {
    setData(null)
    run()
    if (intervalMs <= 0) return
    const timer = window.setInterval(() => {
      if (!document.hidden) run()
    }, intervalMs)
    const onVisible = () => {
      if (!document.hidden) run()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      generation.current++
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, error, loading, updatedAt, refresh: run }
}

/** A clock that ticks every second (for "updated 5s ago"). */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}

/** Is the viewport narrow (phone)? */
export function useNarrow(maxWidth = 720): boolean {
  const query = `(max-width: ${maxWidth}px)`
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const list = window.matchMedia(query)
    const onChange = () => setNarrow(list.matches)
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }, [query])
  return narrow
}

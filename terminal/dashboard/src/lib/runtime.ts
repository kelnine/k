// How the forward paper runtime is doing, from the status it last wrote to
// system_state['paper.runtime'] (docs/12 §12.7) and the API's staleness check.

import type { FeedStatus, RuntimeView } from '../api/types'

export type HealthTone = 'ok' | 'warn' | 'bad' | 'info' | 'muted'

export interface RuntimeHealth {
  tone: HealthTone
  label: string
  detail: string | null
}

/** Statuses during which the runtime writes its status at least every minute. */
const ACTIVE = new Set(['starting', 'warming_up', 'running'])

export function runtimeHealth(view: RuntimeView | null | undefined): RuntimeHealth {
  if (!view) return { tone: 'muted', label: 'runtime …', detail: null }
  if (!view.present)
    return { tone: 'muted', label: 'no forward session', detail: 'the forward runtime has never reported' }
  const status = view.status
  if (!status) return { tone: 'bad', label: 'status unreadable', detail: view.error }
  const state = (status.status ?? '').toLowerCase()
  if (state === 'error') return { tone: 'bad', label: 'runtime error', detail: status.error ?? 'no reason given' }
  if (state === 'stopped') return { tone: 'warn', label: 'stopped', detail: 'not trading: the runtime was stopped' }
  if (ACTIVE.has(state) && view.stale) {
    const age = view.age_seconds === null ? 'a while' : `${Math.round(view.age_seconds)} s`
    return { tone: 'bad', label: 'runtime silent', detail: `${state.replace('_', ' ')}, but no update for ${age}` }
  }
  if (state === 'running') return { tone: 'ok', label: 'running', detail: null }
  if (state === 'starting' || state === 'warming_up')
    return { tone: 'info', label: state.replace('_', ' '), detail: 'warming up or replaying; nothing trades yet' }
  return { tone: 'warn', label: state || 'unknown', detail: null }
}

const FEED_TONES: Record<string, HealthTone> = { ok: 'ok', stale: 'warn', closed: 'muted', no_provider: 'bad' }

/** A feed's state as the runtime reports it: ok, stale, closed (market closed) or no_provider. */
export function feedTone(feed: Pick<FeedStatus, 'state'>): HealthTone {
  return FEED_TONES[(feed.state ?? '').toLowerCase()] ?? 'muted'
}

export function feedLabel(feed: Pick<FeedStatus, 'state'>): string {
  const state = (feed.state ?? '').toLowerCase()
  if (state === 'no_provider') return 'no provider'
  if (state === 'closed') return 'market closed'
  return state || 'unknown'
}

/** Feeds ordered for attention: problems first, then alphabetically. */
export function feedsByAttention(feeds: Record<string, FeedStatus>): [string, FeedStatus][] {
  const rank: Record<HealthTone, number> = { bad: 0, warn: 1, info: 2, ok: 3, muted: 4 }
  return Object.entries(feeds).sort(
    ([a, fa], [b, fb]) => rank[feedTone(fa)] - rank[feedTone(fb)] || a.localeCompare(b),
  )
}

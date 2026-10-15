import { describe, expect, it } from 'vitest'
import type { FeedStatus, RuntimeStatus, RuntimeView } from '../api/types'
import { feedLabel, feedsByAttention, feedTone, runtimeHealth } from './runtime'

function status(overrides: Partial<RuntimeStatus> = {}): RuntimeStatus {
  return {
    session_id: 's1',
    run_id: 'r1',
    status: 'running',
    started_at: '2026-01-05T21:00:00Z',
    updated_at: '2026-01-05T22:00:05Z',
    last_batch_close: '2026-01-05T22:00:00Z',
    instruments: {},
    instances: {},
    kill_switch: { global: false, accounts: [], strategies: [] },
    error: null,
    ...overrides,
  }
}

function view(overrides: Partial<RuntimeView> = {}, runtime: Partial<RuntimeStatus> = {}): RuntimeView {
  return {
    present: true,
    stale: false,
    age_seconds: 5,
    stale_after_seconds: 120,
    status: status(runtime),
    error: null,
    ...overrides,
  }
}

function feed(state: string | null): FeedStatus {
  return { provider: 'oanda', last_bar_open: null, lag_seconds: null, state, last_error: null }
}

describe('runtimeHealth', () => {
  it('handles a terminal without a forward session', () => {
    expect(runtimeHealth(null).label).toBe('runtime …')
    const none = runtimeHealth(view({ present: false, status: null, stale: true, age_seconds: null }))
    expect(none).toMatchObject({ tone: 'muted', label: 'no forward session' })
  })

  it('reports a running runtime as healthy until it goes silent', () => {
    expect(runtimeHealth(view())).toEqual({ tone: 'ok', label: 'running', detail: null })
    const silent = runtimeHealth(view({ stale: true, age_seconds: 605 }))
    expect(silent.tone).toBe('bad')
    expect(silent.label).toBe('runtime silent')
    expect(silent.detail).toBe('running, but no update for 605 s')
  })

  it('shows the reason of a runtime error', () => {
    const failed = runtimeHealth(view({}, { status: 'error', error: 'DataSourceError: no source for XAUUSD' }))
    expect(failed).toEqual({ tone: 'bad', label: 'runtime error', detail: 'DataSourceError: no source for XAUUSD' })
  })

  it('does not call a stopped runtime silent', () => {
    expect(runtimeHealth(view({ stale: true, age_seconds: 9000 }, { status: 'stopped' }))).toMatchObject({
      tone: 'warn',
      label: 'stopped',
    })
  })

  it('shows warm-up and start-up as informational', () => {
    expect(runtimeHealth(view({}, { status: 'warming_up' }))).toMatchObject({ tone: 'info', label: 'warming up' })
    expect(runtimeHealth(view({}, { status: 'starting' }))).toMatchObject({ tone: 'info', label: 'starting' })
  })

  it('flags a status document the API could not read', () => {
    expect(runtimeHealth(view({ status: null, error: 'the runtime status could not be read' }))).toEqual({
      tone: 'bad',
      label: 'status unreadable',
      detail: 'the runtime status could not be read',
    })
  })
})

describe('feeds', () => {
  it('maps the runtime feed states', () => {
    expect(feedTone(feed('ok'))).toBe('ok')
    expect(feedTone(feed('stale'))).toBe('warn')
    expect(feedTone(feed('closed'))).toBe('muted')
    expect(feedTone(feed('no_provider'))).toBe('bad')
    expect(feedTone(feed(null))).toBe('muted')
    expect(feedLabel(feed('no_provider'))).toBe('no provider')
    expect(feedLabel(feed('closed'))).toBe('market closed')
  })

  it('lists problems first', () => {
    const order = feedsByAttention({
      XAUUSD: feed('ok'),
      BTCUSDT: feed('closed'),
      EURUSD: feed('no_provider'),
      NEARUSD: feed('stale'),
      ETHUSDT: feed('ok'),
    }).map(([symbol]) => symbol)
    expect(order).toEqual(['EURUSD', 'NEARUSD', 'ETHUSDT', 'XAUUSD', 'BTCUSDT'])
  })
})

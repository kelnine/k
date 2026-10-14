import { describe, expect, it } from 'vitest'
import type { Account, Metrics } from '../api/types'
import { DEFAULT_SORT, facets, filterAccounts, nextSort, sortAccounts, timeframeMinutes, totals } from './leaderboard'

function metrics(overrides: Partial<Metrics>): Metrics {
  return {
    starting_balance: '50000',
    balance: '50000',
    equity: '50000',
    equity_at: null,
    open_pnl: '0',
    net_pnl: '0',
    return_pct: '0',
    trades: 0,
    wins: 0,
    losses: 0,
    scratches: 0,
    win_rate: null,
    gross_profit: '0',
    gross_loss: '0',
    profit_factor: null,
    average_r: null,
    realized_r: '0',
    avg_winner: null,
    avg_loser: null,
    expectancy: null,
    max_drawdown: null,
    max_drawdown_pct: null,
    open_positions: 0,
    low_sample: true,
    last_trade_at: null,
    ...overrides,
  }
}

function account(id: string, definition: string, instruments: string[], timeframe: string, m: Partial<Metrics>, params = {}): Account {
  return {
    id,
    name: `Paper 50K · ${id}`,
    kind: 'FORWARD',
    mode: 'PAPER',
    broker: 'paper',
    status: 'ACTIVE',
    currency: 'USD',
    instance_id: id,
    instance_name: id,
    definition_id: definition,
    definition_name: definition.replace('_', ' '),
    run_id: null,
    run_kind: null,
    run_name: null,
    version: {
      id: `v-${id}`,
      config_hash: 'h',
      definition_version: '1.0.0',
      code_hash: null,
      params,
      timeframe,
      context_timeframes: [],
      instruments,
      created_at: '2026-01-01T00:00:00Z',
    },
    metrics: metrics(m),
    halted: false,
    runtime: null,
    created_at: '2026-01-01T00:00:00Z',
  }
}

const A = account('ema_xau_5m', 'ema_cross', ['XAUUSD'], '5m', { average_r: '0.40', net_pnl: '900', profit_factor: '1.8', return_pct: '1.8', trades: 40, max_drawdown_pct: '2.10' }, { fast: 9 })
const B = account('ema_xau_15m', 'ema_cross', ['XAUUSD'], '15m', { average_r: '0.40', net_pnl: '1200', profit_factor: '2.1', return_pct: '2.4', trades: 12, max_drawdown_pct: '1.20' }, { fast: 20 })
const C = account('orb_mnq_5m', 'orb', ['MNQ'], '5m', { average_r: '-0.10', net_pnl: '-300', profit_factor: '0.8', return_pct: '-0.6', trades: 31, max_drawdown_pct: '3.00' })
const D = account('sniper_btc_1h', 'sniper', ['BTCUSD', 'SOLUSD'], '1h', {})
const ALL = [A, B, C, D]

describe('sorting', () => {
  it('ranks by expectancy in R by default, ties broken by profit factor', () => {
    expect(sortAccounts(ALL, DEFAULT_SORT).map((a) => a.id)).toEqual(['ema_xau_15m', 'ema_xau_5m', 'orb_mnq_5m', 'sniper_btc_1h'])
  })

  it('keeps accounts without a value last in both directions', () => {
    const asc = sortAccounts(ALL, { key: 'net_pnl', dir: 'asc' })
    expect(asc.map((a) => a.id)).toEqual(['orb_mnq_5m', 'sniper_btc_1h', 'ema_xau_5m', 'ema_xau_15m'])
    const byDd = sortAccounts(ALL, { key: 'max_drawdown_pct', dir: 'asc' }).map((a) => a.id)
    expect(byDd).toEqual(['ema_xau_15m', 'ema_xau_5m', 'orb_mnq_5m', 'sniper_btc_1h'])
    const byDdDesc = sortAccounts(ALL, { key: 'max_drawdown_pct', dir: 'desc' }).map((a) => a.id)
    expect(byDdDesc[byDdDesc.length - 1]).toBe('sniper_btc_1h')
  })

  it('sorts by trades, return and name', () => {
    expect(sortAccounts(ALL, { key: 'trades', dir: 'desc' }).map((a) => a.metrics.trades)).toEqual([40, 31, 12, 0])
    expect(sortAccounts(ALL, { key: 'return_pct', dir: 'desc' })[0].id).toBe('ema_xau_15m')
    expect(sortAccounts(ALL, { key: 'instance', dir: 'asc' }).map((a) => a.id)).toEqual(['ema_xau_15m', 'ema_xau_5m', 'orb_mnq_5m', 'sniper_btc_1h'])
  })

  it('does not reorder its input', () => {
    const before = ALL.map((a) => a.id)
    sortAccounts(ALL, { key: 'net_pnl', dir: 'desc' })
    expect(ALL.map((a) => a.id)).toEqual(before)
  })

  it('flips the same column and starts new columns best-first', () => {
    expect(nextSort(DEFAULT_SORT, 'average_r')).toEqual({ key: 'average_r', dir: 'asc' })
    expect(nextSort(DEFAULT_SORT, 'net_pnl')).toEqual({ key: 'net_pnl', dir: 'desc' })
    expect(nextSort(DEFAULT_SORT, 'max_drawdown_pct')).toEqual({ key: 'max_drawdown_pct', dir: 'asc' })
  })
})

describe('filtering', () => {
  it('filters by strategy, instrument and timeframe', () => {
    expect(filterAccounts(ALL, { strategy: 'ema_cross' }).map((a) => a.id)).toEqual(['ema_xau_5m', 'ema_xau_15m'])
    expect(filterAccounts(ALL, { instrument: 'SOLUSD' }).map((a) => a.id)).toEqual(['sniper_btc_1h'])
    expect(filterAccounts(ALL, { timeframe: '5m' }).map((a) => a.id)).toEqual(['ema_xau_5m', 'orb_mnq_5m'])
    expect(filterAccounts(ALL, { strategy: 'ema_cross', timeframe: '15m' }).map((a) => a.id)).toEqual(['ema_xau_15m'])
  })

  it('searches ids, names, instruments and parameters, case-insensitively', () => {
    expect(filterAccounts(ALL, { query: 'MNQ' }).map((a) => a.id)).toEqual(['orb_mnq_5m'])
    expect(filterAccounts(ALL, { query: 'fast=20' }).map((a) => a.id)).toEqual(['ema_xau_15m'])
    expect(filterAccounts(ALL, { query: '  EMA CROSS ' }).length).toBe(2)
    expect(filterAccounts(ALL, { query: 'nothing like this' })).toEqual([])
  })

  it('offers the filter values present, timeframes in time order', () => {
    const f = facets(ALL)
    expect(f.strategies.map((s) => s.id)).toEqual(['ema_cross', 'orb', 'sniper'])
    expect(f.instruments).toEqual(['BTCUSD', 'MNQ', 'SOLUSD', 'XAUUSD'])
    expect(f.timeframes).toEqual(['5m', '15m', '1h'])
    expect(timeframeMinutes('4h')).toBe(240)
    expect(timeframeMinutes('bogus')).toBe(Number.MAX_SAFE_INTEGER)
  })

  it('totals the shown accounts', () => {
    const t = totals([A, C])
    expect(t.netPnl).toBe(600)
    expect(t.start).toBe(100000)
    expect(t.trades).toBe(71)
  })
})

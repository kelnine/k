import { describe, expect, it } from 'vitest'
import type { TradeMarker } from '../api/types'
import { barIndexAt, instanceColor, tradeLevels, tradeTooltip } from '../kcharts/trades'
import { isChartTimeframe, prependCandles, toCandles, toChartTrades } from './chartData'

const MARKER: TradeMarker = {
  trade_id: 't1',
  account_id: 'a1',
  instance_id: 'demo_sma_fast',
  timeframe: '5m',
  direction: 'SHORT',
  status: 'OPEN',
  qty: '0.0900000000',
  entry_time: '2026-01-14T03:50:00Z',
  entry_price: '4345.7800000000',
  exit_time: null,
  exit_price: null,
  exit_reason: null,
  initial_stop: '4372.2200000000',
  initial_target: '4293.2900000000',
  current_stop: '4360.0000000000',
  current_target: null,
  net_pnl: null,
  r_multiple: null,
}

describe('candles', () => {
  it('converts API bars to KCharts candles', () => {
    const [c] = toCandles([{ t: '2026-01-14T03:45:00Z', o: '4329.79', h: '4356.48', l: '4324.48', c: '4346.49', v: null }])
    expect(c).toEqual({ time: Date.parse('2026-01-14T03:45:00Z'), open: 4329.79, high: 4356.48, low: 4324.48, close: 4346.49, volume: 0 })
  })

  it('prepends older pages without duplicates', () => {
    const loaded = [{ time: 3, open: 1, high: 1, low: 1, close: 1, volume: 0 }]
    const older = [1, 2, 3].map((time) => ({ time, open: 1, high: 1, low: 1, close: 1, volume: 0 }))
    expect(prependCandles(loaded, older).map((c) => c.time)).toEqual([1, 2, 3])
  })

  it('knows the chart timeframes', () => {
    expect(isChartTimeframe('15m')).toBe(true)
    expect(isChartTimeframe('1D')).toBe(false)
    expect(isChartTimeframe(null)).toBe(false)
  })
})

describe('trades on the chart', () => {
  it('uses the current stop and target of open trades, falling back to the initial ones', () => {
    const [t] = toChartTrades([MARKER])
    expect(t.open).toBe(true)
    expect(t.stop).toBe(4360)
    expect(t.target).toBe(4293.29)
    expect(t.entryTime).toBe(Date.parse('2026-01-14T03:50:00Z'))
    expect(t.color).toBe(instanceColor('demo_sma_fast'))
  })

  it('uses the initial levels of closed trades', () => {
    const [t] = toChartTrades([
      { ...MARKER, status: 'CLOSED', exit_time: '2026-01-14T04:10:00Z', exit_price: '4330.00', net_pnl: '142.02', r_multiple: '0.6' },
    ])
    expect(t.stop).toBe(4372.22)
    expect(t.exitTime).toBe(Date.parse('2026-01-14T04:10:00Z'))
    expect(tradeLevels(t, false)).toEqual([4345.78, 4330])
    expect(tradeLevels(t, true)).toEqual([4345.78, 4330, 4372.22, 4293.29])
    expect(tradeTooltip(t)).toBe('Short demo_sma_fast @ 4,345.78 → 4,330.00  +142.02 (+0.60R)')
  })

  it('describes open trades with their levels', () => {
    const [t] = toChartTrades([MARKER])
    expect(tradeTooltip(t)).toBe('Short demo_sma_fast @ 4,345.78 · open  SL 4,360.00  TP 4,293.29')
  })

  it('finds the bar a time falls in', () => {
    const bars = [0, 300, 600, 1200].map((s) => ({ time: s * 1000, open: 1, high: 1, low: 1, close: 1, volume: 0 }))
    expect(barIndexAt(bars, -1)).toBe(-1)
    expect(barIndexAt(bars, 0)).toBe(0)
    expect(barIndexAt(bars, 299_999)).toBe(0)
    expect(barIndexAt(bars, 300_000)).toBe(1)
    expect(barIndexAt(bars, 900_000)).toBe(2) // inside a gap: the last bar before it
    expect(barIndexAt(bars, 5_000_000)).toBe(3)
    expect(barIndexAt([], 0)).toBe(-1)
  })

  it('gives every strategy a stable colour', () => {
    expect(instanceColor('orb_ny_15_mnq')).toBe(instanceColor('orb_ny_15_mnq'))
    expect(instanceColor('a')).toMatch(/^#[0-9a-f]{6}$/)
    const colours = new Set(['s1', 's2', 's3', 's4', 's5', 's6'].map(instanceColor))
    expect(colours.size).toBeGreaterThan(2)
  })
})

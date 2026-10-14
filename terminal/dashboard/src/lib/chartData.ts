// API candles and trade markers → the KCharts engine's types.

import type { Candle as ApiCandle, TradeMarker } from '../api/types'
import { instanceColor, type ChartTrade } from '../kcharts/trades'
import type { Candle } from '../kcharts/types'
import { toNumber } from './format'

export const CHART_TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h'] as const
export type ChartTimeframe = (typeof CHART_TIMEFRAMES)[number]

export const TIMEFRAME_MS: Record<ChartTimeframe, number> = {
  '1m': 60_000,
  '5m': 300_000,
  '15m': 900_000,
  '30m': 1_800_000,
  '1h': 3_600_000,
  '4h': 14_400_000,
}

export function isChartTimeframe(value: string | null | undefined): value is ChartTimeframe {
  return !!value && (CHART_TIMEFRAMES as readonly string[]).includes(value)
}

export function toCandles(rows: ApiCandle[]): Candle[] {
  return rows.map((row) => ({
    time: Date.parse(row.t),
    open: Number(row.o),
    high: Number(row.h),
    low: Number(row.l),
    close: Number(row.c),
    volume: toNumber(row.v) ?? 0,
  }))
}

export function toChartTrades(markers: TradeMarker[]): ChartTrade[] {
  return markers.map((m) => {
    const open = m.status === 'OPEN'
    return {
      id: m.trade_id,
      label: m.instance_id,
      color: instanceColor(m.instance_id),
      direction: m.direction,
      open,
      entryTime: Date.parse(m.entry_time),
      entryPrice: Number(m.entry_price),
      exitTime: m.exit_time ? Date.parse(m.exit_time) : null,
      exitPrice: toNumber(m.exit_price),
      stop: open ? toNumber(m.current_stop ?? m.initial_stop) : toNumber(m.initial_stop),
      target: open ? toNumber(m.current_target ?? m.initial_target) : toNumber(m.initial_target),
      qty: Number(m.qty),
      pnl: toNumber(m.net_pnl),
      r: toNumber(m.r_multiple),
    }
  })
}

/** Merge a page of older candles in front of the loaded ones (no duplicates). */
export function prependCandles(loaded: Candle[], older: Candle[]): Candle[] {
  const first = loaded.length ? loaded[0].time : Infinity
  return [...older.filter((c) => c.time < first), ...loaded]
}

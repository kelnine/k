// K Terminal: trades on the KCharts engine — entry/exit markers, the line between
// them, and stop/target levels. The geometry-free parts live here so they can be
// unit-tested; ChartEngine draws them (see "K Terminal:" in chart.ts).

import type { Candle } from './types'
import { formatPrice } from './utils'

export interface ChartTrade {
  id: string
  /** strategy instance id, shown in tooltips */
  label: string
  /** the instance's colour */
  color: string
  direction: 'LONG' | 'SHORT'
  open: boolean
  entryTime: number // ms epoch of the entry fill
  entryPrice: number
  exitTime: number | null
  exitPrice: number | null
  /** current stop for open trades, initial stop for closed ones */
  stop: number | null
  target: number | null
  qty: number
  pnl: number | null
  r: number | null
}

/** Index of the bar containing time `t` (the last bar opening at or before it); −1 before
 *  the first bar. Bars are in time order (KCharts `Candle.time` is the bar open). */
export function barIndexAt(candles: Candle[], t: number): number {
  let lo = 0
  let hi = candles.length - 1
  if (hi < 0 || t < candles[0].time) return -1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (candles[mid].time <= t) lo = mid
    else hi = mid - 1
  }
  return lo
}

/** Price levels a trade adds to the visible price range: entry and exit always; the
 *  stop and target while it is open or selected (so its risk is on screen). */
export function tradeLevels(trade: ChartTrade, selected: boolean): number[] {
  const levels = [trade.entryPrice]
  if (trade.exitPrice !== null) levels.push(trade.exitPrice)
  if (trade.open || selected) {
    if (trade.stop !== null) levels.push(trade.stop)
    if (trade.target !== null) levels.push(trade.target)
  }
  return levels
}

function signed(value: number, digits: number): string {
  const text = Math.abs(value).toFixed(digits)
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text
}

/** One-line description shown when hovering a marker. */
export function tradeTooltip(trade: ChartTrade): string {
  const side = trade.direction === 'LONG' ? 'Long' : 'Short'
  const entry = `${side} ${trade.label} @ ${formatPrice(trade.entryPrice)}`
  if (trade.open) {
    const stop = trade.stop !== null ? `  SL ${formatPrice(trade.stop)}` : ''
    const target = trade.target !== null ? `  TP ${formatPrice(trade.target)}` : ''
    return `${entry} · open${stop}${target}`
  }
  const exit = trade.exitPrice !== null ? ` → ${formatPrice(trade.exitPrice)}` : ''
  const pnl = trade.pnl !== null ? `  ${signed(trade.pnl, 2)}` : ''
  const r = trade.r !== null ? ` (${signed(trade.r, 2)}R)` : ''
  return `${entry}${exit}${pnl}${r}`
}

const PALETTE = [
  '#2962ff',
  '#ff9800',
  '#ab47bc',
  '#26c6da',
  '#fdd835',
  '#ec407a',
  '#8d6e63',
  '#66bb6a',
  '#5c6bc0',
  '#ffa726',
  '#78909c',
  '#d4e157',
]

/** A stable colour per strategy instance (same id → same colour on every page). */
export function instanceColor(id: string): string {
  let hash = 2166136261
  for (let i = 0; i < id.length; i++) {
    hash ^= id.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return PALETTE[(hash >>> 0) % PALETTE.length]
}

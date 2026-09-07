import type { Candle, Trade } from './types'

/**
 * Footprint (orderflow) aggregation.
 *
 * A footprint bar splits a candle into fixed-height price rows and, for each
 * row, records how much volume traded into the bid versus into the ask:
 *
 *   bid  — aggressive sells (the buyer was the maker, so a seller hit the bid)
 *   ask  — aggressive buys  (the seller was the maker, so a buyer lifted the ask)
 *
 * That split is what turns a candle into a footprint: the same OHLC can be
 * built by patient buyers or by panicking sellers, and only the bid/ask
 * breakdown tells them apart.
 */

export interface FootprintLevel {
  price: number // row low edge (rows span [price, price + rowSize))
  bid: number
  ask: number
}

export interface FootprintBar extends Candle {
  /** rows in ascending price order, contiguous across the traded range */
  levels: FootprintLevel[]
  bidTotal: number
  askTotal: number
  /** ask - bid: net aggression inside the bar */
  delta: number
  /** total traded volume (bid + ask), which can differ from candle volume */
  flowVolume: number
  /** row price with the most volume — the point of control */
  poc: number
  trades: number
}

export interface FootprintSeries {
  bars: FootprintBar[]
  rowSize: number
  /** rolling 10-bar sum of delta; null until the window fills */
  cumDelta: (number | null)[]
  /** percent change of cum delta vs the previous bar */
  roc: (number | null)[]
  /** oldest trade timestamp the tick window reached */
  coverageFrom: number
  /** trades folded into the series */
  tradeCount: number
}

/** Rolling window used for cumulative delta, matching the reference chart. */
const CUM_DELTA_WINDOW = 10

const NICE_STEPS = [1, 2, 2.5, 5, 10]

/**
 * Pick a row height that puts roughly `targetRows` rows inside a typical
 * candle: nice round numbers only, never finer than the exchange tick.
 */
export function chooseRowSize(candles: Candle[], targetRows: number, tick: number | null): number {
  const ranges = candles.map((c) => c.high - c.low).filter((r) => r > 0).sort((a, b) => a - b)
  const typical = ranges.length
    ? ranges[Math.floor(ranges.length * 0.6)]
    : (candles[0]?.close ?? 1) * 0.002
  const rough = typical / Math.max(1, targetRows)
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  let step = mag * 10
  for (const m of NICE_STEPS) {
    if (mag * m >= rough) {
      step = mag * m
      break
    }
  }
  if (tick && tick > 0) {
    // snap to a whole number of exchange ticks, and never go below one tick
    step = Math.max(tick, Math.round(step / tick) * tick)
  }
  return step
}

/** Row index on the absolute price grid, so rows line up across bars. */
function rowOf(price: number, rowSize: number): number {
  return Math.floor(price / rowSize + 1e-9)
}

function emptyLevels(fromRow: number, toRow: number, rowSize: number): FootprintLevel[] {
  const out: FootprintLevel[] = []
  for (let r = fromRow; r <= toRow; r++) out.push({ price: r * rowSize, bid: 0, ask: 0 })
  return out
}

/** Widen a bar's contiguous row range so `row` is inside it. */
function ensureRow(bar: FootprintBar, row: number, rowSize: number): FootprintLevel {
  const levels = bar.levels
  if (levels.length === 0) {
    levels.push({ price: row * rowSize, bid: 0, ask: 0 })
    return levels[0]
  }
  const first = rowOf(levels[0].price, rowSize)
  const last = first + levels.length - 1
  if (row < first) {
    levels.unshift(...emptyLevels(row, first - 1, rowSize))
    return levels[0]
  }
  if (row > last) {
    levels.push(...emptyLevels(last + 1, row, rowSize))
    return levels[levels.length - 1]
  }
  return levels[row - first]
}

function blankBar(c: Candle): FootprintBar {
  return {
    ...c,
    levels: [],
    bidTotal: 0,
    askTotal: 0,
    delta: 0,
    flowVolume: 0,
    poc: c.close,
    trades: 0,
  }
}

/** Fold one print into a bar. Exported for the live path. */
export function applyTrade(bar: FootprintBar, t: Trade, rowSize: number): void {
  const level = ensureRow(bar, rowOf(t.price, rowSize), rowSize)
  if (t.buyerMaker) {
    level.bid += t.qty
    bar.bidTotal += t.qty
  } else {
    level.ask += t.qty
    bar.askTotal += t.qty
  }
  bar.trades += 1
}

/** Recompute the derived per-bar fields after its levels changed. */
export function finalizeBar(bar: FootprintBar): void {
  bar.delta = bar.askTotal - bar.bidTotal
  bar.flowVolume = bar.askTotal + bar.bidTotal
  let best = -1
  for (const l of bar.levels) {
    const v = l.bid + l.ask
    if (v > best) {
      best = v
      bar.poc = l.price
    }
  }
}

/**
 * Diagonal imbalance in [-1, 1] for each row, matching the reference chart:
 * bid volume at a row against ask volume one row *above* it, since those two
 * are the sides that trade against each other as price steps down.
 *
 *   > 0  sellers dominate the diagonal   < 0  buyers dominate
 *
 * The top row has no row above it and inherits its neighbour's value.
 */
export function rowImbalances(levels: FootprintLevel[]): number[] {
  const n = levels.length
  const out = new Array<number>(n).fill(0)
  for (let i = 0; i < n - 1; i++) {
    const bid = levels[i].bid
    const ask = levels[i + 1].ask
    const sum = bid + ask
    out[i] = sum > 0 ? (bid - ask) / sum : 0
  }
  if (n > 1) out[n - 1] = out[n - 2]
  return out
}

/** Rolling cum-delta and its rate of change, as the reference computes them. */
export function seriesMetrics(bars: FootprintBar[]): {
  cumDelta: (number | null)[]
  roc: (number | null)[]
} {
  const cumDelta: (number | null)[] = []
  const roc: (number | null)[] = []
  let running = 0
  for (let i = 0; i < bars.length; i++) {
    running += bars[i].delta
    if (i >= CUM_DELTA_WINDOW) running -= bars[i - CUM_DELTA_WINDOW].delta
    cumDelta.push(i >= CUM_DELTA_WINDOW - 1 ? running : null)
  }
  for (let i = 0; i < bars.length; i++) {
    const cur = cumDelta[i]
    const prev = i > 0 ? cumDelta[i - 1] : null
    roc.push(cur !== null && prev !== null && prev !== 0 ? ((cur - prev) / Math.abs(prev)) * 100 : null)
  }
  return { cumDelta, roc }
}

/**
 * Bucket raw trades onto candles. Candles the tick window doesn't fully cover
 * are dropped — a half-filled footprint bar is worse than no bar at all.
 */
export function buildFootprint(
  candles: Candle[],
  trades: Trade[],
  tfMs: number,
  rowSize: number,
): FootprintSeries {
  const coverageFrom = trades.length ? trades[0].time : Infinity
  const usable = candles.filter((c) => c.time >= coverageFrom)
  const byTime = new Map<number, FootprintBar>()
  const bars = usable.map((c) => {
    const bar = blankBar(c)
    byTime.set(c.time, bar)
    return bar
  })

  for (const t of trades) {
    const bar = byTime.get(Math.floor(t.time / tfMs) * tfMs)
    if (bar) applyTrade(bar, t, rowSize)
  }
  for (const bar of bars) finalizeBar(bar)

  const { cumDelta, roc } = seriesMetrics(bars)
  return {
    bars,
    rowSize,
    cumDelta,
    roc,
    coverageFrom: trades.length ? coverageFrom : 0,
    tradeCount: trades.length,
  }
}

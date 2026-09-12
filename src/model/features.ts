import type { Candle } from '../data/types'
import type { Leg, StructureEvent, Swing, Zone } from './types'

/**
 * Causal feature layer for the Frankenstein ensemble.
 *
 * Every series here is safe to read at bar `i` using only bars `0…i`, and every
 * derived object (zone, structure event, leg) carries the bar index at which it
 * first becomes *knowable* — swings need `strength` bars of confirmation, so a
 * pivot at bar 40 is not visible to the model until bar 45. Without that the
 * back-test would quietly peek into the future and print fantasy equity curves.
 */

export interface Features {
  ema21: (number | null)[]
  ema50: (number | null)[]
  ema200: (number | null)[]
  rsi14: (number | null)[]
  atr14: (number | null)[]
  macdHist: (number | null)[]
  vwap: (number | null)[]
  volAvg: (number | null)[]
  /** ATR as a fraction of price, ranked 0…1 against the trailing window */
  atrPct: (number | null)[]
  swings: Swing[]
  events: StructureEvent[]
  zones: Zone[]
  legs: Leg[]
  /** equal-high / equal-low liquidity pools, keyed by the bar they are known at */
  pools: LiquidityPool[]
}

export interface LiquidityPool {
  price: number
  side: 'high' | 'low'
  known: number
  /** bar the pool was swept, or null */
  swept: number | null
}

export interface FeatureOptions {
  swing: number
  eqTol: number
}

export const FEATURE_DEFAULTS: FeatureOptions = { swing: 5, eqTol: 0.0012 }

// ---------------------------------------------------------------- series math

export function ema(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  const k = 2 / (n + 1)
  let prev: number | null = null
  let seed = 0
  for (let i = 0; i < values.length; i++) {
    if (prev === null) {
      seed += values[i]
      if (i === n - 1) prev = seed / n
    } else {
      prev = values[i] * k + prev * (1 - k)
    }
    out[i] = prev
  }
  return out
}

export function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= n) sum -= values[i - n]
    if (i >= n - 1) out[i] = sum / n
  }
  return out
}

export function rsi(closes: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null)
  let gain = 0
  let loss = 0
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    const g = Math.max(d, 0)
    const l = Math.max(-d, 0)
    if (i <= n) {
      gain += g / n
      loss += l / n
      if (i === n) out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss)
    } else {
      gain = (gain * (n - 1) + g) / n
      loss = (loss * (n - 1) + l) / n
      out[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss)
    }
  }
  return out
}

export function atr(candles: Candle[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(candles.length).fill(null)
  let prev: number | null = null
  let seed = 0
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]
    const pc = i > 0 ? candles[i - 1].close : c.open
    const tr = Math.max(c.high - c.low, Math.abs(c.high - pc), Math.abs(c.low - pc))
    if (prev === null) {
      seed += tr
      if (i === n - 1) prev = seed / n
    } else {
      prev = (prev * (n - 1) + tr) / n
    }
    out[i] = prev
  }
  return out
}

/** Rank of each value inside a trailing window, 0 (lowest seen) … 1 (highest). */
function rollingRank(values: (number | null)[], window: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v === null) continue
    let count = 0
    let seen = 0
    for (let j = Math.max(0, i - window + 1); j <= i; j++) {
      const w = values[j]
      if (w === null) continue
      seen++
      if (w <= v) count++
    }
    out[i] = seen > 1 ? (count - 1) / (seen - 1) : 0.5
  }
  return out
}

// ---------------------------------------------------------------- structure

export function detectSwings(candles: Candle[], L: number): Swing[] {
  const n = candles.length
  const swings: Swing[] = []
  for (let i = L; i < n - L; i++) {
    let isHigh = true
    let isLow = true
    for (let k = 1; k <= L; k++) {
      const h = candles[i].high
      const l = candles[i].low
      if (!(h > candles[i - k].high && h >= candles[i + k].high)) isHigh = false
      if (!(l < candles[i - k].low && l <= candles[i + k].low)) isLow = false
      if (!isHigh && !isLow) break
    }
    if (isHigh) swings.push({ idx: i, price: candles[i].high, kind: 'H', confirm: i + L })
    if (isLow) swings.push({ idx: i, price: candles[i].low, kind: 'L', confirm: i + L })
  }
  return swings
}

/** Walk the bars once, emitting BOS/CHoCH events and the order blocks behind them. */
function walkStructure(
  candles: Candle[],
  swings: Swing[],
): { events: StructureEvent[]; zones: Zone[] } {
  const n = candles.length
  const confirmAt: Swing[][] = Array.from({ length: n }, () => [])
  for (const s of swings) if (s.confirm < n) confirmAt[s.confirm].push(s)

  const events: StructureEvent[] = []
  const zones: Zone[] = []
  let trend = 0
  let lastH: Swing | null = null
  let lastL: Swing | null = null
  let crossedH = false
  let crossedL = false

  for (let t = 0; t < n; t++) {
    for (const s of confirmAt[t]) {
      if (s.kind === 'H') {
        lastH = s
        crossedH = false
      } else {
        lastL = s
        crossedL = false
      }
    }
    const close = candles[t].close
    if (lastH && !crossedH && close > lastH.price) {
      events.push({ bar: t, side: 'bull', type: trend === -1 ? 'CHoCH' : 'BOS', level: lastH.price })
      const ob = lastOppositeCandle(candles, lastH.idx, t, 'bull')
      if (ob !== null) zones.push(makeOrderBlock(candles, ob, t, 'bull'))
      crossedH = true
      trend = 1
    }
    if (lastL && !crossedL && close < lastL.price) {
      events.push({ bar: t, side: 'bear', type: trend === 1 ? 'CHoCH' : 'BOS', level: lastL.price })
      const ob = lastOppositeCandle(candles, lastL.idx, t, 'bear')
      if (ob !== null) zones.push(makeOrderBlock(candles, ob, t, 'bear'))
      crossedL = true
      trend = -1
    }
  }
  return { events, zones }
}

/** Last down-close before a bullish break (or up-close before a bearish one). */
function lastOppositeCandle(
  candles: Candle[],
  fromIdx: number,
  t: number,
  side: 'bull' | 'bear',
): number | null {
  for (let j = t - 1; j >= Math.max(0, fromIdx - 1); j--) {
    const down = candles[j].close < candles[j].open
    if (side === 'bull' ? down : !down) return j
  }
  return null
}

function makeOrderBlock(candles: Candle[], j: number, breakBar: number, side: 'bull' | 'bear'): Zone {
  const top = candles[j].high
  const bottom = candles[j].low
  let until: number | null = null
  for (let m = breakBar + 1; m < candles.length; m++) {
    // an order block dies once price closes through it
    if (side === 'bull' ? candles[m].close < bottom : candles[m].close > top) {
      until = m
      break
    }
  }
  return { kind: 'ob', side, top, bottom, from: j, known: breakBar, until }
}

function detectFvgs(candles: Candle[]): Zone[] {
  const n = candles.length
  const zones: Zone[] = []
  for (let i = 1; i < n - 1; i++) {
    const prevH = candles[i - 1].high
    const prevL = candles[i - 1].low
    const nextH = candles[i + 1].high
    const nextL = candles[i + 1].low
    if (nextL > prevH) {
      zones.push({ kind: 'fvg', side: 'bull', top: nextL, bottom: prevH, from: i - 1, known: i + 1, until: fillBar(candles, i + 2, prevH, 'bull') })
    } else if (nextH < prevL) {
      zones.push({ kind: 'fvg', side: 'bear', top: prevL, bottom: nextH, from: i - 1, known: i + 1, until: fillBar(candles, i + 2, prevL, 'bear') })
    }
  }
  return zones
}

function fillBar(candles: Candle[], start: number, edge: number, side: 'bull' | 'bear'): number | null {
  for (let m = start; m < candles.length; m++) {
    if (side === 'bull' ? candles[m].low <= edge : candles[m].high >= edge) return m
  }
  return null
}

/** Impulse legs between alternating confirmed swings — anchors for fib levels. */
function buildLegs(swings: Swing[]): Leg[] {
  const legs: Leg[] = []
  for (let i = 1; i < swings.length; i++) {
    const a = swings[i - 1]
    const b = swings[i]
    if (a.kind === b.kind) continue
    legs.push({
      from: a.idx,
      to: b.idx,
      fromPrice: a.price,
      toPrice: b.price,
      side: b.kind === 'H' ? 'bull' : 'bear',
      known: b.confirm,
    })
  }
  return legs
}

/** Equal highs / lows: resting liquidity that price tends to reach for. */
function buildPools(candles: Candle[], swings: Swing[], tol: number): LiquidityPool[] {
  const pools: LiquidityPool[] = []
  for (const kind of ['H', 'L'] as const) {
    const pts = swings.filter((s) => s.kind === kind)
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1]
      const b = pts[i]
      const avg = (a.price + b.price) / 2
      if (Math.abs(a.price - b.price) / avg > tol) continue
      const known = b.confirm
      let swept: number | null = null
      for (let m = known; m < candles.length; m++) {
        if (kind === 'H' ? candles[m].high > avg : candles[m].low < avg) {
          swept = m
          break
        }
      }
      pools.push({ price: avg, side: kind === 'H' ? 'high' : 'low', known, swept })
    }
  }
  return pools
}

// ---------------------------------------------------------------- entry point

export function buildFeatures(candles: Candle[], opts: Partial<FeatureOptions> = {}): Features {
  const o = { ...FEATURE_DEFAULTS, ...opts }
  const closes = candles.map((c) => c.close)
  const swings = detectSwings(candles, o.swing)
  const { events, zones: obs } = walkStructure(candles, swings)

  const macdFast = ema(closes, 12)
  const macdSlow = ema(closes, 26)
  const macdLine: (number | null)[] = closes.map((_, i) =>
    macdFast[i] !== null && macdSlow[i] !== null ? macdFast[i]! - macdSlow[i]! : null,
  )
  const first = macdLine.findIndex((v) => v !== null)
  const signal: (number | null)[] = new Array(macdLine.length).fill(null)
  if (first >= 0) {
    const tail = ema(macdLine.slice(first) as number[], 9)
    for (let i = 0; i < tail.length; i++) signal[first + i] = tail[i]
  }
  const macdHist = macdLine.map((v, i) => (v !== null && signal[i] !== null ? v - signal[i]! : null))

  // daily-anchored VWAP
  const vwap: (number | null)[] = new Array(candles.length).fill(null)
  let day = -1
  let pv = 0
  let vol = 0
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]
    const d = Math.floor(c.time / 86_400_000)
    if (d !== day) {
      day = d
      pv = 0
      vol = 0
    }
    pv += ((c.high + c.low + c.close) / 3) * c.volume
    vol += c.volume
    vwap[i] = vol > 0 ? pv / vol : null
  }

  const atr14 = atr(candles, 14)
  const atrPct = rollingRank(
    atr14.map((v, i) => (v === null ? null : v / candles[i].close)),
    120,
  )

  return {
    ema21: ema(closes, 21),
    ema50: ema(closes, 50),
    ema200: ema(closes, 200),
    rsi14: rsi(closes, 14),
    atr14,
    macdHist,
    vwap,
    volAvg: sma(candles.map((c) => c.volume), 20),
    atrPct,
    swings,
    events,
    zones: [...obs, ...detectFvgs(candles)],
    legs: buildLegs(swings),
    pools: buildPools(candles, swings, o.eqTol),
  }
}

/** Zones the model is allowed to see at bar `i` and that are still live. */
export function activeZones(zones: Zone[], i: number): Zone[] {
  return zones.filter((z) => z.known <= i && (z.until === null || z.until > i))
}

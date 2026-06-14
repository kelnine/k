import type { Candle } from '../data/types'
import type { IndicatorDef, IndicatorResult, IndicatorShape } from './index'

/**
 * Phantom Flow SMC — a Smart Money Concepts overlay.
 *
 * From raw candles it derives, with no third-party library:
 *   • Swing structure        — fractal swing highs/lows tagged HH / HL / LH / LL
 *   • Market structure        — BOS (continuation) and CHoCH (reversal) breaks
 *   • Order blocks            — last opposite candle before a structure break,
 *                               drawn as a zone until price mitigates it
 *   • Fair value gaps         — 3-candle imbalances, drawn until filled
 *   • Liquidity               — equal highs / lows (resting liquidity pools)
 *
 * Everything is emitted as `shapes` (boxes / lines / markers) in
 * (candle-index, price) space, which the engine renders on the main pane.
 */

export interface SmcOptions {
  /** fractal strength: bars required on each side of a swing pivot */
  swing: number
  /** equal high/low tolerance, as a fraction of price */
  eqTol: number
  /** keep at most this many order blocks per side */
  maxOB: number
  /** keep at most this many fair value gaps */
  maxFVG: number
  /** keep at most this many swing markers (most recent) */
  maxMarkers: number
}

const DEFAULTS: SmcOptions = {
  swing: 5,
  eqTol: 0.001,
  maxOB: 6,
  maxFVG: 14,
  maxMarkers: 40,
}

// phantom palette: green = bullish, red = bearish, violet = neutral accents
const C = {
  bull: '38,166,154',
  bear: '239,83,80',
  muted: 'rgba(139,147,163,0.85)',
  eq: 'rgba(139,147,163,0.65)',
}

interface Swing {
  idx: number
  price: number
  confirm: number // bar index at which this swing is confirmed (idx + swing)
  kind: 'H' | 'L'
}

function detectSwings(candles: Candle[], L: number): Swing[] {
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
    if (isHigh) swings.push({ idx: i, price: candles[i].high, confirm: i + L, kind: 'H' })
    if (isLow) swings.push({ idx: i, price: candles[i].low, confirm: i + L, kind: 'L' })
  }
  return swings
}

export function makeSmc(opts: Partial<SmcOptions> = {}): IndicatorDef {
  const o: SmcOptions = { ...DEFAULTS, ...opts }
  return {
    id: 'phantomflow',
    name: 'Phantom Flow SMC',
    kind: 'overlay',
    compute: (candles) => compute(candles, o),
  }
}

function compute(candles: Candle[], o: SmcOptions): IndicatorResult {
  const n = candles.length
  const shapes: IndicatorShape[] = []
  if (n < o.swing * 2 + 3) {
    return { plots: [], shapes, legend: [{ color: C.muted, value: '—' }] }
  }

  const swings = detectSwings(candles, o.swing)

  // ---- fair value gaps (3-candle imbalance), drawn until filled
  const fvgs: IndicatorShape[] = []
  const SCAN = 400 // cap forward fill search for performance
  for (let i = 1; i < n - 1; i++) {
    const prevH = candles[i - 1].high
    const prevL = candles[i - 1].low
    const nextH = candles[i + 1].high
    const nextL = candles[i + 1].low
    if (nextL > prevH) {
      // bullish gap between prev high and next low
      let x2: number | null = null
      for (let m = i + 2; m < Math.min(n, i + 2 + SCAN); m++) {
        if (candles[m].low <= prevH) {
          x2 = m
          break
        }
      }
      fvgs.push({ type: 'box', x1: i - 1, x2, yTop: nextL, yBottom: prevH, fill: `rgba(${C.bull},0.07)` })
    } else if (nextH < prevL) {
      // bearish gap between prev low and next high
      let x2: number | null = null
      for (let m = i + 2; m < Math.min(n, i + 2 + SCAN); m++) {
        if (candles[m].high >= prevL) {
          x2 = m
          break
        }
      }
      fvgs.push({ type: 'box', x1: i - 1, x2, yTop: prevL, yBottom: nextH, fill: `rgba(${C.bear},0.07)` })
    }
  }

  // ---- market structure (BOS / CHoCH) + order blocks
  const confirmAt: Swing[][] = Array.from({ length: n }, () => [])
  for (const s of swings) if (s.confirm < n) confirmAt[s.confirm].push(s)

  const structureLines: IndicatorShape[] = []
  const bullOBs: IndicatorShape[] = []
  const bearOBs: IndicatorShape[] = []
  let trend = 0 // 1 bull, -1 bear
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
      const type = trend === -1 ? 'CHoCH' : 'BOS'
      structureLines.push({
        type: 'line',
        x1: lastH.idx,
        x2: t,
        y1: lastH.price,
        y2: lastH.price,
        color: `rgba(${C.bull},0.9)`,
        dash: type === 'CHoCH' ? [5, 4] : undefined,
        label: type,
        labelColor: `rgba(${C.bull},1)`,
      })
      const ob = lastBullOB(candles, lastH.idx, t)
      if (ob !== null) bullOBs.push(makeOB(candles, ob, t, 'bull'))
      crossedH = true
      trend = 1
    }
    if (lastL && !crossedL && close < lastL.price) {
      const type = trend === 1 ? 'CHoCH' : 'BOS'
      structureLines.push({
        type: 'line',
        x1: lastL.idx,
        x2: t,
        y1: lastL.price,
        y2: lastL.price,
        color: `rgba(${C.bear},0.9)`,
        dash: type === 'CHoCH' ? [5, 4] : undefined,
        label: type,
        labelColor: `rgba(${C.bear},1)`,
      })
      const ob = lastBearOB(candles, lastL.idx, t)
      if (ob !== null) bearOBs.push(makeOB(candles, ob, t, 'bear'))
      crossedL = true
      trend = -1
    }
  }

  // ---- equal highs / lows (resting liquidity)
  const eqLines: IndicatorShape[] = []
  pushEqual(swings, 'H', o.eqTol, eqLines)
  pushEqual(swings, 'L', o.eqTol, eqLines)

  // ---- swing markers (HH / HL / LH / LL)
  const markers: IndicatorShape[] = []
  let prevHigh: number | null = null
  let prevLow: number | null = null
  for (const s of swings) {
    if (s.kind === 'H') {
      const label = prevHigh === null ? 'HH' : s.price > prevHigh ? 'HH' : 'LH'
      prevHigh = s.price
      markers.push({ type: 'marker', x: s.idx, y: s.price, text: label, color: C.muted, place: 'above' })
    } else {
      const label = prevLow === null ? 'HL' : s.price < prevLow ? 'LL' : 'HL'
      prevLow = s.price
      markers.push({ type: 'marker', x: s.idx, y: s.price, text: label, color: C.muted, place: 'below' })
    }
  }

  // ---- assemble (faint zones first, structure on top, markers last)
  shapes.push(...fvgs.slice(-o.maxFVG))
  shapes.push(...bullOBs.slice(-o.maxOB))
  shapes.push(...bearOBs.slice(-o.maxOB))
  shapes.push(...eqLines.slice(-6))
  shapes.push(...structureLines)
  shapes.push(...markers.slice(-o.maxMarkers))

  const trendLabel = trend === 1 ? 'Bullish' : trend === -1 ? 'Bearish' : 'Neutral'
  const trendColor = trend === 1 ? `rgba(${C.bull},1)` : trend === -1 ? `rgba(${C.bear},1)` : C.muted

  return { plots: [], shapes, legend: [{ color: trendColor, value: trendLabel }] }
}

/** last bearish candle before a bullish break → bullish order block */
function lastBullOB(candles: Candle[], fromIdx: number, t: number): number | null {
  for (let j = t - 1; j >= Math.max(0, fromIdx - 1); j--) {
    if (candles[j].close < candles[j].open) return j
  }
  return null
}

/** last bullish candle before a bearish break → bearish order block */
function lastBearOB(candles: Candle[], fromIdx: number, t: number): number | null {
  for (let j = t - 1; j >= Math.max(0, fromIdx - 1); j--) {
    if (candles[j].close > candles[j].open) return j
  }
  return null
}

function makeOB(candles: Candle[], j: number, breakBar: number, side: 'bull' | 'bear'): IndicatorShape {
  const n = candles.length
  const top = candles[j].high
  const bottom = candles[j].low
  // mitigated when price trades back into the zone after the impulse
  let x2: number | null = null
  for (let m = breakBar + 1; m < n; m++) {
    if (side === 'bull' ? candles[m].low <= top : candles[m].high >= bottom) {
      x2 = m
      break
    }
  }
  const color = side === 'bull' ? C.bull : C.bear
  return {
    type: 'box',
    x1: j,
    x2,
    yTop: top,
    yBottom: bottom,
    fill: `rgba(${color},0.14)`,
    stroke: `rgba(${color},0.55)`,
    label: 'OB',
    labelColor: `rgba(${color},0.95)`,
  }
}

function pushEqual(swings: Swing[], kind: 'H' | 'L', tol: number, out: IndicatorShape[]): void {
  const pts = swings.filter((s) => s.kind === kind)
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]
    const b = pts[i]
    const avg = (a.price + b.price) / 2
    if (Math.abs(a.price - b.price) / avg <= tol) {
      out.push({
        type: 'line',
        x1: a.idx,
        x2: b.idx,
        y1: avg,
        y2: avg,
        color: C.eq,
        dash: [2, 3],
        label: kind === 'H' ? 'EQH' : 'EQL',
        labelColor: C.muted,
      })
    }
  }
}

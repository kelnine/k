import type { Candle } from '../data/types'
import type { IndicatorDef, IndicatorResult, IndicatorShape, Plot } from './index'

/**
 * Jetstream — a from-scratch, free alternative to the kind of premium
 * "buy/sell signal + money-flow wave" indicator packs sold for hundreds of
 * dollars. Nothing here is licensed or lifted; it's built from public,
 * well-understood techniques (ATR trend trail + WaveTrend oscillator) so the
 * whole thing is yours, auditable, and costs nothing.
 *
 * It ships as two registered indicators that are designed to be used together:
 *
 *   • Jetstream Trend (overlay) — an ATR "SuperTrend" trail that paints the
 *     active trend, an EMA ribbon for context, and ▲/▼ signals printed on the
 *     exact bar the trend flips.
 *
 *   • Jetstream Waves (pane) — a WaveTrend money-flow oscillator drawn as a
 *     stack of nested, rainbow-coloured momentum waves with overbought /
 *     oversold guides — the signature "wave" look, computed locally.
 */

// ----------------------------------------------------------------- math

function ema(values: (number | null)[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  const k = 2 / (n + 1)
  let prev: number | null = null
  let seed = 0
  let count = 0
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v === null || v === undefined) {
      out[i] = prev
      continue
    }
    if (prev === null) {
      seed += v
      count++
      if (count === n) prev = seed / n
    } else {
      prev = v * k + prev * (1 - k)
    }
    out[i] = prev
  }
  return out
}

function sma(values: (number | null)[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  let sum = 0
  let count = 0
  const win: number[] = []
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v === null || v === undefined) {
      out[i] = win.length === n ? sum / n : null
      continue
    }
    win.push(v)
    sum += v
    count++
    if (win.length > n) sum -= win.shift()!
    if (win.length === n) out[i] = sum / n
    else out[i] = null
  }
  void count
  return out
}

/** Wilder-smoothed Average True Range. */
function wilderAtr(candles: Candle[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(candles.length).fill(null)
  let atr: number | null = null
  let seed = 0
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]
    const prevClose = i > 0 ? candles[i - 1].close : c.close
    const tr = Math.max(c.high - c.low, Math.abs(c.high - prevClose), Math.abs(c.low - prevClose))
    if (atr === null) {
      seed += tr
      if (i === n - 1) atr = seed / n
    } else {
      atr = (atr * (n - 1) + tr) / n
    }
    out[i] = atr
  }
  return out
}

// ----------------------------------------------------------------- Jetstream Trend

export interface TrendOptions {
  atrLen: number
  mult: number
  fast: number
  slow: number
}

const TREND_DEFAULTS: TrendOptions = { atrLen: 10, mult: 3, fast: 21, slow: 55 }

const COL = {
  bull: '38,166,154',
  bear: '239,83,80',
}

function computeTrend(candles: Candle[], o: TrendOptions): IndicatorResult {
  const n = candles.length
  const atr = wilderAtr(candles, o.atrLen)

  // SuperTrend trail (standard final-band formulation)
  const stUp: (number | null)[] = new Array(n).fill(null) // trail while bullish
  const stDown: (number | null)[] = new Array(n).fill(null) // trail while bearish
  const dir: number[] = new Array(n).fill(1)
  let finalUpper = 0
  let finalLower = 0
  let prevTrend = 1
  let started = false
  const shapes: IndicatorShape[] = []

  for (let i = 0; i < n; i++) {
    const a = atr[i]
    if (a === null) continue
    const c = candles[i]
    const hl2 = (c.high + c.low) / 2
    const upperBand = hl2 + o.mult * a
    const lowerBand = hl2 - o.mult * a
    const prevClose = candles[i - 1].close

    if (!started) {
      finalUpper = upperBand
      finalLower = lowerBand
      prevTrend = 1
      started = true
    } else {
      finalUpper = upperBand < finalUpper || prevClose > finalUpper ? upperBand : finalUpper
      finalLower = lowerBand > finalLower || prevClose < finalLower ? lowerBand : finalLower
    }

    let trend: number
    if (prevTrend === 1) trend = c.close < finalLower ? -1 : 1
    else trend = c.close > finalUpper ? 1 : -1

    dir[i] = trend
    if (trend === 1) stUp[i] = finalLower
    else stDown[i] = finalUpper

    // print a signal on the bar where the trend flips
    if (started && trend !== prevTrend) {
      if (trend === 1) {
        shapes.push({
          type: 'marker',
          x: i,
          y: c.low,
          text: '▲ BUY',
          color: `rgba(${COL.bull},1)`,
          place: 'below',
        })
      } else {
        shapes.push({
          type: 'marker',
          x: i,
          y: c.high,
          text: '▼ SELL',
          color: `rgba(${COL.bear},1)`,
          place: 'above',
        })
      }
    }
    prevTrend = trend
  }

  // EMA ribbon for trend context
  const closes = candles.map((c) => c.close)
  const fast = ema(closes, o.fast)
  const slow = ema(closes, o.slow)

  const plots: Plot[] = [
    { key: 'stUp', color: `rgba(${COL.bull},0.95)`, style: 'line', width: 2, values: stUp },
    { key: 'stDown', color: `rgba(${COL.bear},0.95)`, style: 'line', width: 2, values: stDown },
    { key: 'fast', color: 'rgba(120,200,255,0.9)', style: 'line', width: 1, values: fast },
    { key: 'slow', color: 'rgba(255,170,90,0.9)', style: 'line', width: 1, values: slow },
  ]

  const last = dir[n - 1] ?? 1
  const trendLabel = last === 1 ? 'Long' : 'Short'
  const trendColor = last === 1 ? `rgba(${COL.bull},1)` : `rgba(${COL.bear},1)`

  return {
    plots,
    shapes,
    fills: [{ a: 'fast', b: 'slow', color: last === 1 ? `rgba(${COL.bull},0.05)` : `rgba(${COL.bear},0.05)` }],
    legend: [{ color: trendColor, value: trendLabel }],
  }
}

export function makeJetstreamTrend(opts: Partial<TrendOptions> = {}): IndicatorDef {
  const o: TrendOptions = { ...TREND_DEFAULTS, ...opts }
  return {
    id: 'jetstream',
    name: 'Jetstream Trend',
    kind: 'overlay',
    compute: (candles) => computeTrend(candles, o),
  }
}

// ----------------------------------------------------------------- Jetstream Waves

export interface WaveOptions {
  /** channel length (esa / deviation smoothing) */
  n1: number
  /** average length (final wave smoothing) */
  n2: number
  /** signal SMA length */
  sig: number
  /** number of nested rainbow layers */
  layers: number
}

const WAVE_DEFAULTS: WaveOptions = { n1: 10, n2: 21, sig: 4, layers: 6 }

/** evenly spaced spectrum colour for rainbow layer `i` of `total`. */
function rainbow(i: number, total: number, alpha: number): string {
  const hue = 280 - (280 * i) / Math.max(1, total - 1) // violet → red
  return `hsla(${Math.round(hue)}, 85%, 60%, ${alpha})`
}

function computeWaves(candles: Candle[], o: WaveOptions): IndicatorResult {
  const ap = candles.map((c) => (c.high + c.low + c.close) / 3)
  const esa = ema(ap, o.n1)
  const dev = ema(
    ap.map((v, i) => (esa[i] !== null ? Math.abs(v - esa[i]!) : null)),
    o.n1,
  )
  const ci = ap.map((v, i) => {
    const e = esa[i]
    const d = dev[i]
    if (e === null || d === null || d === 0) return null
    return (v - e) / (0.015 * d)
  })
  const wt1 = ema(ci, o.n2)
  const wt2 = sma(wt1, o.sig)

  // nested rainbow layers: progressively smoothed copies of the wave
  const plots: Plot[] = []
  for (let k = 0; k < o.layers; k++) {
    const len = 3 + k * 4
    plots.push({
      key: `wave${k}`,
      color: rainbow(k, o.layers, 0.9),
      style: 'line',
      width: 1,
      values: ema(wt1, len),
    })
  }

  // primary wave + signal on top
  plots.push({ key: 'wt1', color: 'rgba(255,255,255,0.9)', style: 'line', width: 1.5, values: wt1 })
  plots.push({ key: 'wt2', color: 'rgba(120,144,255,0.95)', style: 'line', width: 1, values: wt2 })

  const last = wt1[wt1.length - 1]
  const lastSig = wt2[wt2.length - 1]
  let state = 'Neutral'
  let stateColor = 'rgba(139,147,163,0.9)'
  if (last !== null && lastSig !== null) {
    if (last > lastSig) {
      state = last < -45 ? 'Oversold ↑' : 'Bullish'
      stateColor = `rgba(${COL.bull},1)`
    } else {
      state = last > 45 ? 'Overbought ↓' : 'Bearish'
      stateColor = `rgba(${COL.bear},1)`
    }
  }

  return {
    plots,
    fills: [{ a: 'wt1', b: 'wt2', color: 'rgba(120,144,255,0.15)' }],
    guides: [
      { value: 60, color: 'rgba(239,83,80,0.35)' },
      { value: 0, color: 'rgba(255,255,255,0.12)' },
      { value: -60, color: 'rgba(38,166,154,0.35)' },
    ],
    legend: [{ color: stateColor, value: state }],
  }
}

export function makeJetstreamWaves(opts: Partial<WaveOptions> = {}): IndicatorDef {
  const o: WaveOptions = { ...WAVE_DEFAULTS, ...opts }
  return {
    id: 'jetwaves',
    name: 'Jetstream Waves',
    kind: 'pane',
    compute: (candles) => computeWaves(candles, o),
  }
}

import type { Candle } from '../data/types'
import { makeSmc } from './smc'
import { makeVwapWinner } from './vwap-winner'

export type PlotStyle = 'line' | 'hist'

export interface Plot {
  key: string
  color: string
  style: PlotStyle
  width?: number
  dash?: number[]
  values: (number | null)[]
}

/**
 * Free-form drawing primitives an indicator can emit, positioned in
 * (candle-index, price) space. `x` is a candle index; an `x2` of `null`
 * means "extend to the right edge of the chart". Rendered on the main pane
 * for overlay indicators (used by Phantom Flow SMC for zones / structure).
 */
export interface ShapeBox {
  type: 'box'
  x1: number
  x2: number | null
  yTop: number
  yBottom: number
  fill: string
  stroke?: string
  label?: string
  labelColor?: string
}

export interface ShapeLine {
  type: 'line'
  x1: number
  x2: number | null
  y1: number
  y2: number
  color: string
  width?: number
  dash?: number[]
  label?: string
  labelColor?: string
}

export interface ShapeMarker {
  type: 'marker'
  x: number
  y: number
  text: string
  color: string
  place: 'above' | 'below'
}

export type IndicatorShape = ShapeBox | ShapeLine | ShapeMarker

export interface IndicatorResult {
  plots: Plot[]
  /** horizontal reference lines (oscillator panes) */
  guides?: { value: number; color: string }[]
  /** fixed y-range, e.g. [0, 100] for RSI */
  range?: [number, number]
  /** translucent fill between two plot keys */
  fills?: { a: string; b: string; color: string }[]
  /** free-form overlay primitives (boxes / lines / markers) */
  shapes?: IndicatorShape[]
  /** custom legend chips (used when an indicator has no numeric plots) */
  legend?: { color: string; value: string }[]
}

export interface IndicatorDef {
  id: string
  /** display name incl. params, e.g. "RSI 14" */
  name: string
  kind: 'overlay' | 'pane'
  compute(candles: Candle[]): IndicatorResult
}

// ---------------------------------------------------------------- math

function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= n) sum -= values[i - n]
    if (i >= n - 1) out[i] = sum / n
  }
  return out
}

function ema(values: number[], n: number): (number | null)[] {
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

function rsi(closes: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null)
  let avgGain = 0
  let avgLoss = 0
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    const gain = Math.max(d, 0)
    const loss = Math.max(-d, 0)
    if (i <= n) {
      avgGain += gain / n
      avgLoss += loss / n
      if (i === n) out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
    } else {
      avgGain = (avgGain * (n - 1) + gain) / n
      avgLoss = (avgLoss * (n - 1) + loss) / n
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)
    }
  }
  return out
}

// ---------------------------------------------------------------- registry

const C = {
  blue: '#2962ff',
  orange: '#ff9800',
  purple: '#ab47bc',
  teal: '#26a69a',
  red: '#ef5350',
  yellow: '#fdd835',
  cyan: '#26c6da',
}

function maDef(id: string, name: string, n: number, color: string, exp = false): IndicatorDef {
  return {
    id,
    name,
    kind: 'overlay',
    compute(candles) {
      const closes = candles.map((c) => c.close)
      return { plots: [{ key: 'ma', color, style: 'line', values: exp ? ema(closes, n) : sma(closes, n) }] }
    },
  }
}

export const INDICATORS: IndicatorDef[] = [
  maDef('ma20', 'MA 20', 20, C.yellow),
  maDef('ma50', 'MA 50', 50, C.orange),
  maDef('ma200', 'MA 200', 200, C.red),
  maDef('ema21', 'EMA 21', 21, C.cyan, true),
  {
    id: 'bb',
    name: 'BB 20·2',
    kind: 'overlay',
    compute(candles) {
      const n = 20
      const closes = candles.map((c) => c.close)
      const mid = sma(closes, n)
      const upper: (number | null)[] = new Array(closes.length).fill(null)
      const lower: (number | null)[] = new Array(closes.length).fill(null)
      for (let i = n - 1; i < closes.length; i++) {
        const m = mid[i]!
        let v = 0
        for (let j = i - n + 1; j <= i; j++) v += (closes[j] - m) ** 2
        const sd = Math.sqrt(v / n)
        upper[i] = m + 2 * sd
        lower[i] = m - 2 * sd
      }
      return {
        plots: [
          { key: 'upper', color: C.blue, style: 'line', values: upper },
          { key: 'mid', color: 'rgba(41,98,255,0.6)', style: 'line', values: mid },
          { key: 'lower', color: C.blue, style: 'line', values: lower },
        ],
        fills: [{ a: 'upper', b: 'lower', color: 'rgba(41,98,255,0.06)' }],
      }
    },
  },
  {
    id: 'vwap',
    name: 'VWAP',
    kind: 'overlay',
    compute(candles) {
      // anchored to each UTC day
      const values: (number | null)[] = new Array(candles.length).fill(null)
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
        const typical = (c.high + c.low + c.close) / 3
        pv += typical * c.volume
        vol += c.volume
        values[i] = vol > 0 ? pv / vol : null
      }
      return { plots: [{ key: 'vwap', color: C.purple, style: 'line', values }] }
    },
  },
  makeVwapWinner(),
  {
    id: 'rsi',
    name: 'RSI 14',
    kind: 'pane',
    compute(candles) {
      return {
        plots: [{ key: 'rsi', color: C.purple, style: 'line', values: rsi(candles.map((c) => c.close), 14) }],
        guides: [
          { value: 70, color: 'rgba(239,83,80,0.45)' },
          { value: 30, color: 'rgba(38,166,154,0.45)' },
        ],
        range: [0, 100],
      }
    },
  },
  {
    id: 'macd',
    name: 'MACD 12·26·9',
    kind: 'pane',
    compute(candles) {
      const closes = candles.map((c) => c.close)
      const fast = ema(closes, 12)
      const slow = ema(closes, 26)
      const macd: (number | null)[] = closes.map((_, i) =>
        fast[i] !== null && slow[i] !== null ? fast[i]! - slow[i]! : null,
      )
      const first = macd.findIndex((v) => v !== null)
      const signal: (number | null)[] = new Array(macd.length).fill(null)
      if (first >= 0) {
        const tail = ema(macd.slice(first) as number[], 9)
        for (let i = 0; i < tail.length; i++) signal[first + i] = tail[i]
      }
      const hist = macd.map((v, i) =>
        v !== null && signal[i] !== null ? v - signal[i]! : null,
      )
      return {
        plots: [
          { key: 'hist', color: C.teal, style: 'hist', values: hist },
          { key: 'macd', color: C.blue, style: 'line', values: macd },
          { key: 'signal', color: C.orange, style: 'line', values: signal },
        ],
        guides: [{ value: 0, color: 'rgba(255,255,255,0.15)' }],
      }
    },
  },
  makeSmc(),
]

export function indicatorById(id: string): IndicatorDef | undefined {
  return INDICATORS.find((d) => d.id === id)
}

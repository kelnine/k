import type { Candle } from '../data/types'
import type { IndicatorDef, IndicatorResult, IndicatorShape, IndicatorTable, TablePart } from './index'

/**
 * Profit Gang v1.0 — an ICT-style execution overlay.
 *
 * From raw candles it derives:
 *   • Swing signals   — ▲ / ▼ triangles at confirmed major swing points
 *   • CISD            — Change In the State of Delivery: the open of the last
 *                       opposite-direction delivery leg; a close through it
 *                       prints a dotted +CISD / -CISD level and a zone drawn
 *                       from the broken leg until price closes back through
 *   • SH / SL         — the unbroken external structure high / low, extended
 *                       to the right edge
 *   • Bias dashboard  — a pinned table with live Swing / CISD status plus
 *                       HTF (daily) and MTF (h1) CISD & open bias, resampled
 *                       from the loaded series
 */

export interface ProfitGangOptions {
  /** fractal strength for structure swings (SH/SL + swing status) */
  swing: number
  /** fractal strength for the big ▲ / ▼ swing signals */
  signalSwing: number
  /** minimum candles in a delivery leg for its break to count as CISD */
  minRun: number
  /** keep at most this many CISD level lines */
  maxLevels: number
  /** keep at most this many CISD zones per side */
  maxZones: number
  /** keep at most this many ▲ / ▼ signals */
  maxSignals: number
}

const DEFAULTS: ProfitGangOptions = {
  swing: 5,
  signalSwing: 10,
  minRun: 2,
  maxLevels: 8,
  maxZones: 3,
  maxSignals: 12,
}

const BULL = '#089981'
const BEAR = '#e5342c'
const NEUTRAL = '#8b93a3'
const STRUCT = '#2962ff'

export function makeProfitGang(opts: Partial<ProfitGangOptions> = {}): IndicatorDef {
  const o: ProfitGangOptions = { ...DEFAULTS, ...opts }
  return {
    id: 'profitgang',
    name: 'Profit Gang v1.0',
    kind: 'overlay',
    compute: (candles) => compute(candles, o),
  }
}

// ---------------------------------------------------------------- swings

interface Swing {
  idx: number
  price: number
  confirm: number
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

// ---------------------------------------------------------------- CISD

interface Run {
  start: number
  open: number
  high: number
  low: number
  len: number
  dir: 1 | -1
}

interface CisdEvent {
  breakBar: number
  start: number
  level: number
  high: number
  low: number
  dir: 1 | -1
}

/** delivery legs = runs of consecutive same-direction closes; a close through
 *  the open of the last opposite leg is a change in the state of delivery */
function detectCisd(candles: Candle[], minRun: number): { events: CisdEvent[]; state: number } {
  const events: CisdEvent[] = []
  let cur: Run | null = null
  let lastUp: Run | null = null
  let lastDown: Run | null = null
  let state = 0

  for (let t = 0; t < candles.length; t++) {
    const c = candles[t]
    const dir: 1 | -1 = c.close >= c.open ? 1 : -1
    if (!cur || cur.dir !== dir) {
      if (cur) {
        if (cur.dir === 1) lastUp = cur
        else lastDown = cur
      }
      cur = { start: t, open: c.open, high: c.high, low: c.low, len: 1, dir }
    } else {
      cur.high = Math.max(cur.high, c.high)
      cur.low = Math.min(cur.low, c.low)
      cur.len++
    }
    if (lastDown && c.close > lastDown.open) {
      if (lastDown.len >= minRun) {
        events.push({ breakBar: t, start: lastDown.start, level: lastDown.open, high: lastDown.high, low: lastDown.low, dir: 1 })
      }
      state = 1
      lastDown = null
    }
    if (lastUp && c.close < lastUp.open) {
      if (lastUp.len >= minRun) {
        events.push({ breakBar: t, start: lastUp.start, level: lastUp.open, high: lastUp.high, low: lastUp.low, dir: -1 })
      }
      state = -1
      lastUp = null
    }
  }
  return { events, state }
}

// ---------------------------------------------------------------- HTF/MTF bias

function resample(candles: Candle[], bucketMs: number): Candle[] {
  const out: Candle[] = []
  for (const c of candles) {
    const t = Math.floor(c.time / bucketMs) * bucketMs
    const last = out[out.length - 1]
    if (last && last.time === t) {
      last.high = Math.max(last.high, c.high)
      last.low = Math.min(last.low, c.low)
      last.close = c.close
      last.volume += c.volume
    } else {
      out.push({ time: t, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume })
    }
  }
  return out
}

/** chart candle interval, inferred as the median gap between recent candles */
function inferTfMs(candles: Candle[]): number {
  const diffs: number[] = []
  for (let i = Math.max(1, candles.length - 50); i < candles.length; i++) {
    diffs.push(candles[i].time - candles[i - 1].time)
  }
  diffs.sort((a, b) => a - b)
  return diffs[Math.floor(diffs.length / 2)] || 60_000
}

/**
 * CISD bias and open bias of the series resampled to `bucketMs`;
 * 0 = not derivable (bucket smaller than the source candles, or too few of them)
 */
function seriesBias(candles: Candle[], tfMs: number, bucketMs: number): { cisd: number; open: number } {
  if (bucketMs < tfMs) return { cisd: 0, open: 0 }
  const series = resample(candles, bucketMs)
  if (series.length < 3) return { cisd: 0, open: 0 }
  const { state } = detectCisd(series, 1)
  const cur = series[series.length - 1]
  return { cisd: state, open: cur.close >= cur.open ? 1 : -1 }
}

function biasPart(prefix: string, bias: number): TablePart {
  if (bias === 0) return { text: `${prefix}: —`, color: '#666' }
  return { text: `${prefix}: ${bias > 0 ? 'Bullish' : 'Bearish'}`, color: bias > 0 ? BULL : BEAR }
}

// ---------------------------------------------------------------- compute

function compute(candles: Candle[], o: ProfitGangOptions): IndicatorResult {
  const n = candles.length
  const shapes: IndicatorShape[] = []
  if (n < o.signalSwing * 2 + 3) {
    return { plots: [], shapes, legend: [{ color: NEUTRAL, value: '—' }] }
  }

  // ---- CISD levels + zones
  const { events, state: cisdState } = detectCisd(candles, o.minRun)
  const levelLines: IndicatorShape[] = []
  const bullZones: IndicatorShape[] = []
  const bearZones: IndicatorShape[] = []
  for (const ev of events) {
    const color = ev.dir === 1 ? BULL : BEAR
    levelLines.push({
      type: 'line',
      x1: ev.start,
      x2: ev.breakBar,
      y1: ev.level,
      y2: ev.level,
      color,
      dash: [2, 3],
      label: ev.dir === 1 ? '+CISD' : '-CISD',
      labelColor: color,
    })
    levelLines.push({ type: 'marker', x: ev.start, y: ev.level, text: '+', color, place: ev.dir === 1 ? 'below' : 'above' })
    // zone = the broken delivery leg, extended until price closes back through the level
    let x2: number | null = null
    for (let m = ev.breakBar + 1; m < n; m++) {
      if (ev.dir === 1 ? candles[m].close < ev.level : candles[m].close > ev.level) {
        x2 = m
        break
      }
    }
    const zone: IndicatorShape = {
      type: 'box',
      x1: ev.start,
      x2,
      yTop: ev.dir === 1 ? ev.level : ev.high,
      yBottom: ev.dir === 1 ? ev.low : ev.level,
      fill: ev.dir === 1 ? 'rgba(8,153,129,0.13)' : 'rgba(229,52,44,0.10)',
    }
    if (ev.dir === 1) bullZones.push(zone)
    else bearZones.push(zone)
  }

  // ---- structure swings → swing status + unbroken SH / SL
  const swings = detectSwings(candles, o.swing)
  const confirmAt: Swing[][] = Array.from({ length: n }, () => [])
  for (const s of swings) if (s.confirm < n) confirmAt[s.confirm].push(s)

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
      crossedH = true
      trend = 1
    }
    if (lastL && !crossedL && close < lastL.price) {
      crossedL = true
      trend = -1
    }
  }

  const structLines: IndicatorShape[] = []
  if (lastH && !crossedH) {
    structLines.push({
      type: 'line',
      x1: lastH.idx,
      x2: null,
      y1: lastH.price,
      y2: lastH.price,
      color: STRUCT,
      label: 'SH',
      labelColor: STRUCT,
    })
  }
  if (lastL && !crossedL) {
    structLines.push({
      type: 'line',
      x1: lastL.idx,
      x2: null,
      y1: lastL.price,
      y2: lastL.price,
      color: STRUCT,
      label: 'SL',
      labelColor: STRUCT,
    })
  }

  // ---- big ▲ / ▼ swing signals
  const signals: IndicatorShape[] = detectSwings(candles, o.signalSwing).map((s) =>
    s.kind === 'H'
      ? { type: 'marker', x: s.idx, y: s.price, text: '▼', color: BEAR, place: 'above', size: 15 }
      : { type: 'marker', x: s.idx, y: s.price, text: '▲', color: BULL, place: 'below', size: 15 },
  )

  // ---- HTF / MTF bias dashboard
  const tfMs = inferTfMs(candles)
  const htf = seriesBias(candles, tfMs, 86_400_000)
  const mtf = seriesBias(candles, tfMs, 3_600_000)
  const swingPart: TablePart =
    trend === 0
      ? { text: 'Swing: —', color: '#666' }
      : { text: `Swing: ${trend > 0 ? 'Bullish' : 'Bearish'}`, color: trend > 0 ? BULL : BEAR }
  const cisdPart: TablePart =
    cisdState === 0
      ? { text: 'CISD: —', color: '#666' }
      : { text: `CISD: ${cisdState > 0 ? 'Bullish' : 'Bearish'}`, color: cisdState > 0 ? BULL : BEAR }
  const sep: TablePart = { text: '  |  ', color: '#444' }

  const table: IndicatorTable = {
    title: 'Profit Gang v1.0',
    rows: [
      { label: 'Swing Status', parts: [swingPart], bg: '#ffffff' },
      { label: 'CISD Status', parts: [cisdPart], bg: '#ffffff' },
      { label: 'HTF/MTF CISD Bias', parts: [biasPart('HTF D', htf.cisd), sep, biasPart('MTF h1', mtf.cisd)], bg: '#efdcb9' },
      { label: 'HTF/MTF Open Bias', parts: [biasPart('HTF D', htf.open), sep, biasPart('MTF h1', mtf.open)], bg: '#cde8cf' },
    ],
  }

  // ---- assemble (zones first, then levels / structure, signals on top)
  shapes.push(...bullZones.slice(-o.maxZones))
  shapes.push(...bearZones.slice(-o.maxZones))
  shapes.push(...levelLines.slice(-o.maxLevels * 2))
  shapes.push(...structLines)
  shapes.push(...signals.slice(-o.maxSignals))

  const legend = [
    trend === 0
      ? { color: NEUTRAL, value: 'Swing —' }
      : { color: trend > 0 ? BULL : BEAR, value: `Swing ${trend > 0 ? 'Bullish' : 'Bearish'}` },
    cisdState === 0
      ? { color: NEUTRAL, value: 'CISD —' }
      : { color: cisdState > 0 ? BULL : BEAR, value: `CISD ${cisdState > 0 ? 'Bullish' : 'Bearish'}` },
  ]

  return { plots: [], shapes, table, legend }
}

import type { Candle } from '../data/types'
import type { IndicatorDef, IndicatorResult, IndicatorShape } from './index'

/**
 * SMC Liquidity Setup — a four-stage, multi-timeframe liquidity model.
 *
 *   1. Weekly sweep   — price takes out the previous week's high or low
 *                       (optionally only once the level is reclaimed)
 *   2. HTF key level  — price then trades into a higher-timeframe fair value
 *                       gap and/or a higher-timeframe support/resistance pivot
 *   3. MSS            — an intermediate-timeframe market structure shift
 *                       breaks the last confirmed swing in the sweep direction
 *   4. Entry trigger  — a chart-timeframe inverse FVG and/or CISD fires
 *
 * The stages are strictly ordered and directional: a fresh sweep on one side
 * arms that side and disarms the other, a sweep of both sides on the same bar
 * is ambiguous and arms neither, and everything resets on the weekly open.
 *
 * All three timeframes are derived from the chart's own candles by bucketing,
 * so the indicator works on any timeframe at or below the MSS timeframe. Every
 * higher-timeframe value is held back until the bucket that produced it has
 * closed, so nothing on the chart repaints.
 */

export type ZoneMode = 'fvg-or-sr' | 'fvg' | 'sr' | 'both'
export type ExecMode = 'ifvg-or-cisd' | 'ifvg' | 'cisd' | 'both'

export interface LiquidityOptions {
  /** require price to close back across the swept level before arming */
  requireReclaim: boolean
  /** higher-timeframe bucket for FVG / S/R zones, ms */
  htfMs: number
  /** fractal strength for higher-timeframe S/R pivots */
  htfPivot: number
  /** S/R zone half-width, as a multiple of higher-timeframe ATR(14) */
  srAtrTol: number
  zoneMode: ZoneMode
  /** bucket for the market structure shift, ms */
  mssMs: number
  /** fractal strength for MSS swings */
  mssPivot: number
  execMode: ExecMode
  /** keep at most this many higher-timeframe zones per side */
  maxZones: number
  /** draw previous-week levels for at most this many weeks */
  maxWeeks: number
}

const HOUR = 3_600_000
const WEEK = 604_800_000
/** epoch is a Thursday; shift by 4 days so weekly buckets open on Monday UTC */
const WEEK_ANCHOR = 4 * 86_400_000

const DEFAULTS: LiquidityOptions = {
  requireReclaim: true,
  htfMs: HOUR,
  htfPivot: 3,
  srAtrTol: 0.25,
  zoneMode: 'fvg-or-sr',
  mssMs: 15 * 60_000,
  mssPivot: 3,
  execMode: 'ifvg-or-cisd',
  maxZones: 4,
  maxWeeks: 6,
}

const C = {
  bull: '38,166,154',
  bear: '239,83,80',
  sweep: '171,71,188',
  muted: 'rgba(139,147,163,0.85)',
}

// ---------------------------------------------------------------- buckets

interface Bucket {
  start: number
  high: number
  low: number
  close: number
  startIdx: number
  endIdx: number
}

/** Aggregate the chart's candles into higher-timeframe buckets. */
function bucketize(candles: Candle[], size: number, anchor = 0): Bucket[] {
  const out: Bucket[] = []
  let cur: Bucket | null = null
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]
    const start = Math.floor((c.time - anchor) / size) * size + anchor
    if (cur === null || start !== cur.start) {
      cur = { start, high: c.high, low: c.low, close: c.close, startIdx: i, endIdx: i }
      out.push(cur)
    } else {
      cur.high = Math.max(cur.high, c.high)
      cur.low = Math.min(cur.low, c.low)
      cur.close = c.close
      cur.endIdx = i
    }
  }
  return out
}

/**
 * Spread bucket-derived values over the chart's bars. `at` is the first bar
 * index on which a value may be used — always the bar *after* the bucket that
 * produced it closed, which is what keeps higher-timeframe reads causal.
 */
function holdForward<T>(n: number, events: { at: number; value: T }[]): (T | null)[] {
  const out = new Array<T | null>(n).fill(null)
  let e = 0
  let cur: T | null = null
  for (let i = 0; i < n; i++) {
    while (e < events.length && events[e].at <= i) cur = events[e++].value
    out[i] = cur
  }
  return out
}

/** Last confirmed fractal pivot of a bucket series, released on confirmation. */
function pivotEvents(bars: Bucket[], len: number, kind: 'H' | 'L'): { at: number; value: number }[] {
  const out: { at: number; value: number }[] = []
  for (let i = len; i < bars.length - len; i++) {
    let ok = true
    for (let k = 1; k <= len && ok; k++) {
      ok =
        kind === 'H'
          ? bars[i].high > bars[i - k].high && bars[i].high >= bars[i + k].high
          : bars[i].low < bars[i - k].low && bars[i].low <= bars[i + k].low
    }
    if (ok) out.push({ at: bars[i + len].endIdx + 1, value: kind === 'H' ? bars[i].high : bars[i].low })
  }
  return out
}

/** Wilder ATR over a bucket series. */
function bucketAtr(bars: Bucket[], n: number): (number | null)[] {
  const out = new Array<number | null>(bars.length).fill(null)
  let avg: number | null = null
  let seed = 0
  for (let i = 0; i < bars.length; i++) {
    const tr =
      i === 0
        ? bars[0].high - bars[0].low
        : Math.max(
            bars[i].high - bars[i].low,
            Math.abs(bars[i].high - bars[i - 1].close),
            Math.abs(bars[i].low - bars[i - 1].close),
          )
    if (avg === null) {
      seed += tr
      if (i === n - 1) avg = seed / n
    } else {
      avg = (avg * (n - 1) + tr) / n
    }
    out[i] = avg
  }
  return out
}

// ---------------------------------------------------------------- modes

interface Zone {
  top: number
  bottom: number
}

function zoneValid(mode: ZoneMode, fvg: boolean, sr: boolean): boolean {
  return mode === 'fvg' ? fvg : mode === 'sr' ? sr : mode === 'both' ? fvg && sr : fvg || sr
}

function execValid(mode: ExecMode, ifvg: boolean, cisd: boolean): boolean {
  return mode === 'ifvg' ? ifvg : mode === 'cisd' ? cisd : mode === 'both' ? ifvg && cisd : ifvg || cisd
}

const STAGE_TEXT = ['Weekly sweep', 'HTF zone', 'MSS', 'Entry trigger', 'Complete']

export function makeLiquiditySetup(opts: Partial<LiquidityOptions> = {}): IndicatorDef {
  const o: LiquidityOptions = { ...DEFAULTS, ...opts }
  return {
    id: 'liquiditysetup',
    name: 'SMC Liquidity Setup',
    kind: 'overlay',
    compute: (candles) => compute(candles, o),
  }
}

// ---------------------------------------------------------------- compute

function compute(candles: Candle[], o: LiquidityOptions): IndicatorResult {
  const n = candles.length
  const shapes: IndicatorShape[] = []
  if (n < 20) return { plots: [], shapes, legend: [{ color: C.muted, value: '—' }] }

  // ---- previous week's high / low, held for the whole week
  const weeks = bucketize(candles, WEEK, WEEK_ANCHOR)
  const prevWeekHigh = new Array<number | null>(n).fill(null)
  const prevWeekLow = new Array<number | null>(n).fill(null)
  const weekOpen = new Array<boolean>(n).fill(false)
  for (let k = 0; k < weeks.length; k++) {
    // the first bucket may start mid-week, so it is never used as a reference
    const ref = k >= 2 ? weeks[k - 1] : null
    for (let i = weeks[k].startIdx; i <= weeks[k].endIdx; i++) {
      prevWeekHigh[i] = ref ? ref.high : null
      prevWeekLow[i] = ref ? ref.low : null
    }
    if (k > 0) weekOpen[weeks[k].startIdx] = true
  }

  // ---- higher-timeframe fair value gaps
  const htf = bucketize(candles, Math.max(o.htfMs, 1))
  const bullFvgEvents: { at: number; value: Zone }[] = []
  const bearFvgEvents: { at: number; value: Zone }[] = []
  for (let j = 2; j < htf.length; j++) {
    const at = htf[j].endIdx + 1
    if (htf[j].low > htf[j - 2].high) {
      bullFvgEvents.push({ at, value: { top: htf[j].low, bottom: htf[j - 2].high } })
    } else if (htf[j].high < htf[j - 2].low) {
      bearFvgEvents.push({ at, value: { top: htf[j - 2].low, bottom: htf[j].high } })
    }
  }
  const bullFvg = holdForward(n, bullFvgEvents)
  const bearFvg = holdForward(n, bearFvgEvents)

  // ---- higher-timeframe support / resistance and its ATR tolerance
  const htfSupport = holdForward(n, pivotEvents(htf, o.htfPivot, 'L'))
  const htfResistance = holdForward(n, pivotEvents(htf, o.htfPivot, 'H'))
  const atrSeries = bucketAtr(htf, 14)
  const atrEvents: { at: number; value: number }[] = []
  for (let j = 0; j < htf.length; j++) {
    const v = atrSeries[j]
    if (v !== null) atrEvents.push({ at: htf[j].endIdx + 1, value: v })
  }
  const htfAtr = holdForward(n, atrEvents)

  // ---- market structure shift on the intermediate timeframe
  const mss = bucketize(candles, Math.max(o.mssMs, 1))
  const mssHigh = pivotEvents(mss, o.mssPivot, 'H')
  const mssLow = pivotEvents(mss, o.mssPivot, 'L')
  const bullMss = new Array<boolean>(n).fill(false)
  const bearMss = new Array<boolean>(n).fill(false)
  {
    let hi = 0
    let lo = 0
    let lastHigh: number | null = null
    let lastLow: number | null = null
    // the final bucket is still forming, so it is not evaluated
    for (let j = 1; j < mss.length - 1; j++) {
      const at = mss[j].endIdx
      while (hi < mssHigh.length && mssHigh[hi].at <= at) lastHigh = mssHigh[hi++].value
      while (lo < mssLow.length && mssLow[lo].at <= at) lastLow = mssLow[lo++].value
      if (lastHigh !== null && mss[j].close > lastHigh && mss[j - 1].close <= lastHigh) bullMss[at] = true
      if (lastLow !== null && mss[j].close < lastLow && mss[j - 1].close >= lastLow) bearMss[at] = true
    }
  }

  // ---- chart-timeframe entry triggers: inverse FVG and CISD
  const bullTrigger = new Array<boolean>(n).fill(false)
  const bearTrigger = new Array<boolean>(n).fill(false)
  {
    let lastBullFvg: Zone | null = null
    let lastBearFvg: Zone | null = null
    let lastBearishOpen: number | null = null
    let lastBullishOpen: number | null = null
    for (let i = 2; i < n; i++) {
      const c = candles[i]
      const prev = candles[i - 1]

      // a bearish gap reclaimed upward / a bullish gap violated downward
      const ifvgUp = lastBearFvg !== null && c.close > lastBearFvg.top && prev.close <= lastBearFvg.top
      const ifvgDown = lastBullFvg !== null && c.close < lastBullFvg.bottom && prev.close >= lastBullFvg.bottom
      // close back through the open of the latest opposing candle
      const cisdUp = lastBearishOpen !== null && c.close > lastBearishOpen && prev.close <= lastBearishOpen
      const cisdDown = lastBullishOpen !== null && c.close < lastBullishOpen && prev.close >= lastBullishOpen

      bullTrigger[i] = execValid(o.execMode, ifvgUp, cisdUp)
      bearTrigger[i] = execValid(o.execMode, ifvgDown, cisdDown)

      // an inverted gap has done its job and is retired
      if (ifvgUp) lastBearFvg = null
      if (ifvgDown) lastBullFvg = null

      if (c.low > candles[i - 2].high) lastBullFvg = { top: c.low, bottom: candles[i - 2].high }
      if (c.high < candles[i - 2].low) lastBearFvg = { top: candles[i - 2].low, bottom: c.high }
      if (c.close < c.open) lastBearishOpen = c.open
      if (c.close > c.open) lastBullishOpen = c.open
    }
  }

  // ---- stage machine
  const markers: IndicatorShape[] = []
  const signals: IndicatorShape[] = []
  let sellSideTaken = false
  let buySideTaken = false
  let bullSwept = false
  let bearSwept = false
  // a week that takes both sides has no clean directional bias and is skipped
  let weekAmbiguous = false
  let bullStage = 0
  let bearStage = 0

  for (let i = 0; i < n; i++) {
    if (weekOpen[i]) {
      sellSideTaken = false
      buySideTaken = false
      bullSwept = false
      bearSwept = false
      weekAmbiguous = false
      bullStage = 0
      bearStage = 0
    }

    const c = candles[i]
    const pwh = prevWeekHigh[i]
    const pwl = prevWeekLow[i]
    if (pwl !== null && c.low < pwl) sellSideTaken = true
    if (pwh !== null && c.high > pwh) buySideTaken = true

    const bullSweep =
      !weekAmbiguous && !bullSwept && sellSideTaken && pwl !== null && (!o.requireReclaim || c.close > pwl)
    const bearSweep =
      !weekAmbiguous && !bearSwept && buySideTaken && pwh !== null && (!o.requireReclaim || c.close < pwh)
    if (bullSweep) bullSwept = true
    if (bearSweep) bearSwept = true
    if (bullSweep && bearSweep) weekAmbiguous = true

    if (bullSweep || bearSweep) {
      // a clean sweep arms one side and disarms the other; both at once is
      // directionless, so neither side is armed
      bullStage = bullSweep && !bearSweep ? 1 : 0
      bearStage = bearSweep && !bullSweep ? 1 : 0
      if (bullSweep && !bearSweep) {
        markers.push(marker(i, c.low, 'SSL SWEEP', `rgba(${C.sweep},0.95)`, 'below'))
      } else if (bearSweep && !bullSweep) {
        markers.push(marker(i, c.high, 'BSL SWEEP', `rgba(${C.sweep},0.95)`, 'above'))
      }
      continue
    }

    const bFvg = bullFvg[i]
    const sFvg = bearFvg[i]
    const sup = htfSupport[i]
    const res = htfResistance[i]
    const tol = htfAtr[i] === null ? null : htfAtr[i]! * o.srAtrTol

    const bullZone = zoneValid(
      o.zoneMode,
      bFvg !== null && c.high >= bFvg.bottom && c.low <= bFvg.top,
      sup !== null && tol !== null && c.low <= sup + tol && c.high >= sup - tol,
    )
    const bearZone = zoneValid(
      o.zoneMode,
      sFvg !== null && c.high >= sFvg.bottom && c.low <= sFvg.top,
      res !== null && tol !== null && c.high >= res - tol && c.low <= res + tol,
    )

    if (bullStage === 1 && bullZone) bullStage = 2
    else if (bullStage === 2 && bullMss[i]) {
      bullStage = 3
      markers.push(marker(i, c.low, 'MSS', `rgba(${C.bull},0.95)`, 'below'))
    } else if (bullStage === 3 && bullTrigger[i]) {
      bullStage = 4
      signals.push(marker(i, c.low, '▲ LONG', `rgba(${C.bull},1)`, 'below'))
    }

    if (bearStage === 1 && bearZone) bearStage = 2
    else if (bearStage === 2 && bearMss[i]) {
      bearStage = 3
      markers.push(marker(i, c.high, 'MSS', `rgba(${C.bear},0.95)`, 'above'))
    } else if (bearStage === 3 && bearTrigger[i]) {
      bearStage = 4
      signals.push(marker(i, c.high, '▼ SHORT', `rgba(${C.bear},1)`, 'above'))
    }
  }

  // ---- previous-week levels, stepped across each week
  const levels: IndicatorShape[] = []
  for (const w of weeks.slice(-o.maxWeeks)) {
    const hi = prevWeekHigh[w.startIdx]
    const lo = prevWeekLow[w.startIdx]
    if (hi !== null) levels.push(level(w, hi, `rgba(${C.bear},0.7)`, 'PWH'))
    if (lo !== null) levels.push(level(w, lo, `rgba(${C.bull},0.7)`, 'PWL'))
  }

  // ---- higher-timeframe zones, drawn until price fills them
  const zones: IndicatorShape[] = []
  pushZones(candles, bullFvgEvents, 'bull', o.maxZones, zones)
  pushZones(candles, bearFvgEvents, 'bear', o.maxZones, zones)

  shapes.push(...zones, ...levels, ...markers.slice(-40), ...signals)

  const bias = bullStage > 0 ? 'LONG' : bearStage > 0 ? 'SHORT' : 'NONE'
  const stage = Math.max(bullStage, bearStage)
  const color = bullStage > 0 ? `rgba(${C.bull},1)` : bearStage > 0 ? `rgba(${C.bear},1)` : C.muted

  return {
    plots: [],
    shapes,
    legend: [
      { color, value: bias },
      { color: C.muted, value: stage === 4 ? STAGE_TEXT[4] : `next: ${STAGE_TEXT[stage]}` },
    ],
  }
}

function marker(x: number, y: number, text: string, color: string, place: 'above' | 'below'): IndicatorShape {
  return { type: 'marker', x, y, text, color, place }
}

function level(w: Bucket, price: number, color: string, label: string): IndicatorShape {
  return {
    type: 'line',
    x1: w.startIdx,
    x2: w.endIdx,
    y1: price,
    y2: price,
    color,
    dash: [4, 3],
    label,
    labelColor: color,
  }
}

function pushZones(
  candles: Candle[],
  events: { at: number; value: Zone }[],
  side: 'bull' | 'bear',
  keep: number,
  out: IndicatorShape[],
): void {
  const n = candles.length
  const color = side === 'bull' ? C.bull : C.bear
  for (const e of events.slice(-keep)) {
    let x2: number | null = null
    for (let m = e.at; m < n; m++) {
      if (side === 'bull' ? candles[m].low <= e.value.bottom : candles[m].high >= e.value.top) {
        x2 = m
        break
      }
    }
    out.push({
      type: 'box',
      x1: Math.min(e.at, n - 1),
      x2,
      yTop: e.value.top,
      yBottom: e.value.bottom,
      fill: `rgba(${color},0.10)`,
      stroke: `rgba(${color},0.4)`,
      label: 'HTF FVG',
      labelColor: `rgba(${color},0.9)`,
    })
  }
}

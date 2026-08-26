import type { Candle } from '../data/types'
import type { IndicatorDef, IndicatorResult, IndicatorShape, LegendItem } from './index'

/**
 * Multi-Horizon Momentum — a rule-based trend-scoring rubric in the spirit of
 * the AHL / managed-futures time-series momentum work.
 *
 * The rubric measures trend strength instead of predicting it:
 *
 *   1. Score the trend. On each of four lookbacks (1 week, 2 weeks, 1 month,
 *      2 months) draw a line from the close that far back to the latest close.
 *      Rising scores +1, falling scores −1. The four readings sum to a single
 *      market score in the range −4 … +4.
 *   2. Rate it.  +4 fully long · +2 half long · 0 no trade · −2 half short ·
 *      −4 fully short. The score sets direction *and* exposure.
 *   3. Size it.  position = scoreWeight × (targetRisk% / annualisedVol%) × portfolio,
 *      where annualised vol is the average daily close-to-close % move over the
 *      last 30 days scaled by √365 (≈ 19.1). Calm market → bigger size, wild
 *      market → smaller size.
 *
 * The rubric is written for a daily chart. Everything here is expressed in
 * *days* and converted to bars from the candle spacing, so the same rules hold
 * on any timeframe: the lookbacks stay 7/14/30/60 calendar days and volatility
 * is always sampled as a daily close-to-close move.
 */

export interface MomentumOptions {
  /** trend lookbacks, in calendar days */
  lookbackDays: number[]
  /** volatility window: how many daily returns to average */
  volDays: number
  /** % of the account you are willing to lose on this strategy */
  targetRiskPct: number
  /** account size used for the worked position-size figure */
  portfolio: number
}

const DEFAULTS: MomentumOptions = {
  lookbackDays: [7, 14, 30, 60],
  volDays: 30,
  targetRiskPct: 10,
  portfolio: 100_000,
}

const DAY_MS = 86_400_000
const UP = '#26a69a'
const DOWN = '#ef5350'
const MUTED = '#787b86'

/** Median bar spacing, so day-based rules can be expressed in bars. */
function barMs(candles: Candle[]): number {
  const diffs: number[] = []
  for (let i = Math.max(1, candles.length - 200); i < candles.length; i++) {
    const d = candles[i].time - candles[i - 1].time
    if (d > 0) diffs.push(d)
  }
  if (diffs.length === 0) return DAY_MS
  diffs.sort((a, b) => a - b)
  return diffs[diffs.length >> 1]
}

export interface MomentumRating {
  /** sum of the per-horizon ±1 readings */
  score: number
  /** per-horizon readings, in `lookbackDays` order */
  readings: number[]
  /** 1.0 at a full score, 0.5 at half, 0 flat */
  weight: number
  /** "Fully long" / "Half short" / "No trade" */
  signal: string
  /** average daily close-to-close move, annualised, in % */
  annVolPct: number | null
  /** position as a fraction of the portfolio (may exceed 1 = leverage) */
  exposure: number | null
  /** exposure × portfolio, in account currency */
  positionSize: number | null
}

/** Rubric row for a score: exposure weight and its label. */
export function rate(score: number, horizons: number): { weight: number; signal: string } {
  const weight = horizons > 0 ? Math.abs(score) / horizons : 0
  if (weight === 0) return { weight: 0, signal: 'No trade' }
  const side = score > 0 ? 'long' : 'short'
  if (weight === 1) return { weight, signal: `Fully ${side}` }
  if (weight === 0.5) return { weight, signal: `Half ${side}` }
  return { weight, signal: `${Math.round(weight * 100)}% ${side}` }
}

/**
 * Annualised volatility at bar `i`: the average absolute close-to-close move
 * over the last `volDays` daily steps, scaled to a yearly figure by √(365/step).
 */
export function annualisedVol(
  closes: number[],
  i: number,
  stepBars: number,
  samples: number,
  daysPerStep: number,
): number | null {
  const first = i - stepBars * samples
  if (first < 0) return null
  let sum = 0
  let n = 0
  for (let j = i; j > first; j -= stepBars) {
    const prev = closes[j - stepBars]
    if (!(prev > 0)) return null
    sum += Math.abs(closes[j] / prev - 1)
    n++
  }
  if (n === 0) return null
  return (sum / n) * Math.sqrt(365 / daysPerStep) * 100
}

/** Full rubric read-out at bar `i` (defaults to the latest bar). */
export function momentumAt(
  candles: Candle[],
  i: number = candles.length - 1,
  opts: Partial<MomentumOptions> = {},
): MomentumRating | null {
  const o = { ...DEFAULTS, ...opts }
  if (i < 0 || i >= candles.length) return null
  const closes = candles.map((c) => c.close)
  const bar = barMs(candles)
  const lookbacks = o.lookbackDays.map((d) => Math.max(1, Math.round((d * DAY_MS) / bar)))
  if (i < Math.max(...lookbacks)) return null

  // 1 — score each horizon: rising close-to-close is +1, anything else −1
  const readings = lookbacks.map((L) => (closes[i] > closes[i - L] ? 1 : -1))
  const score = readings.reduce((a, b) => a + b, 0)

  // 2 — rate it
  const { weight, signal } = rate(score, lookbacks.length)

  // 3 — size it
  const stepBars = Math.max(1, Math.round(DAY_MS / bar))
  const daysPerStep = (stepBars * bar) / DAY_MS
  const annVolPct = annualisedVol(closes, i, stepBars, o.volDays, daysPerStep)
  const exposure = annVolPct !== null && annVolPct > 0 ? weight * (o.targetRiskPct / annVolPct) : null

  return {
    score,
    readings,
    weight,
    signal,
    annVolPct,
    exposure,
    positionSize: exposure === null ? null : exposure * o.portfolio,
  }
}

function money(v: number): string {
  return '$' + Math.round(v).toLocaleString('en-US')
}

function signed(v: number): string {
  return (v > 0 ? '+' : '') + v
}

function horizonLabel(days: number): string {
  if (days % 30 === 0) return `${days / 30}M`
  if (days % 7 === 0) return `${days / 7}W`
  return `${days}D`
}

/** Pane indicator: the −4 … +4 score as a histogram, with the sizing read-out. */
export function makeMomentum(opts: Partial<MomentumOptions> = {}): IndicatorDef {
  const o = { ...DEFAULTS, ...opts }
  const n = o.lookbackDays.length
  return {
    id: 'mhm',
    name: `Momentum Score ${o.lookbackDays.map(horizonLabel).join('·')}`,
    kind: 'pane',
    compute(candles): IndicatorResult {
      const values: (number | null)[] = new Array(candles.length).fill(null)
      const ratings: (MomentumRating | null)[] = new Array(candles.length).fill(null)
      for (let i = 0; i < candles.length; i++) {
        const r = momentumAt(candles, i, o)
        ratings[i] = r
        values[i] = r ? r.score : null
      }
      const guides = [{ value: 0, color: 'rgba(255,255,255,0.18)' }]
      for (const v of [n, n / 2]) {
        guides.push({ value: v, color: 'rgba(38,166,154,0.35)' })
        guides.push({ value: -v, color: 'rgba(239,83,80,0.35)' })
      }
      return {
        plots: [{ key: 'score', color: UP, style: 'hist', values }],
        guides,
        range: [-(n + 0.8), n + 0.8],
        legend: (i: number): LegendItem[] => {
          const r = ratings[Math.max(0, Math.min(ratings.length - 1, i))]
          if (!r) return [{ color: MUTED, value: 'warming up…' }]
          const tone = r.score > 0 ? UP : r.score < 0 ? DOWN : MUTED
          const items: LegendItem[] = [
            { color: tone, value: signed(r.score) },
            { color: tone, value: r.signal },
            {
              color: MUTED,
              value: r.readings.map((v, k) => `${horizonLabel(o.lookbackDays[k])} ${signed(v)}`).join(' '),
            },
          ]
          if (r.annVolPct !== null) {
            items.push({ color: MUTED, value: `risk ${o.targetRiskPct}% · vol ${r.annVolPct.toFixed(0)}%` })
          }
          if (r.exposure !== null) {
            items.push({
              color: tone,
              value: `size ${(r.exposure * 100).toFixed(1)}% = ${money(r.positionSize!)} of ${money(o.portfolio)}`,
            })
          }
          return items
        },
      }
    },
  }
}

/**
 * Overlay indicator: the four trendlines the rubric asks you to draw — each
 * runs from the close X days ago to the latest close, green when it rises and
 * red when it falls.
 */
export function makeMomentumLines(opts: Partial<MomentumOptions> = {}): IndicatorDef {
  const o = { ...DEFAULTS, ...opts }
  return {
    id: 'mhmlines',
    name: 'Momentum Trendlines',
    kind: 'overlay',
    compute(candles): IndicatorResult {
      const shapes: IndicatorShape[] = []
      const last = candles.length - 1
      if (last < 1) return { plots: [], shapes, legend: [{ color: MUTED, value: 'no data' }] }

      const bar = barMs(candles)
      const rating = momentumAt(candles, last, o)
      const close = candles[last].close
      for (const days of o.lookbackDays) {
        const L = Math.max(1, Math.round((days * DAY_MS) / bar))
        const from = last - L
        if (from < 0) continue
        const up = close > candles[from].close
        // the line itself, plus a tag at its anchor — all four share the
        // same right-hand endpoint, so the label goes on the left
        shapes.push({
          type: 'line',
          x1: from,
          x2: last,
          y1: candles[from].close,
          y2: close,
          color: up ? UP : DOWN,
          width: 2,
        })
        shapes.push({
          type: 'marker',
          x: from,
          y: candles[from].close,
          text: `${horizonLabel(days)} ${up ? '+1' : '\u22121'}`,
          color: up ? UP : DOWN,
          place: up ? 'below' : 'above',
        })
      }

      const tone = !rating ? MUTED : rating.score > 0 ? UP : rating.score < 0 ? DOWN : MUTED
      return {
        plots: [],
        shapes,
        legend: rating
          ? [
              { color: tone, value: signed(rating.score) },
              { color: tone, value: rating.signal },
            ]
          : [{ color: MUTED, value: 'warming up…' }],
      }
    },
  }
}

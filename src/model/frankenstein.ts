import type { Candle } from '../data/types'
import type { Features } from './features'
import { LIMBS, runLimbs, type Limb } from './limbs'
import type { LimbVote, ModelBar } from './types'

/**
 * The ensemble — "the frankenstein model".
 *
 * Nine limbs, none of them clever on its own, stitched into one number per bar:
 *
 *   score  = weighted mean of the limb votes (limbs with no read are excluded,
 *            subject to a floor so one loud limb can't run the whole body)
 *   gate   = 0…1 regime filter — dead-flat and blow-off volatility both shrink
 *            it, and so does the limbs disagreeing with each other
 *   gated  = score × gate — the only number the trader is allowed to act on
 *
 * The gate is what keeps the thing from trading every chop bar: a strong score
 * the limbs disagree about, or a strong score in a regime that can't carry it,
 * gets throttled before it ever reaches the execution layer.
 */

export interface EnsembleOptions {
  /** limbs must supply at least this share of total weight before a score counts */
  activeFloor: number
  /** ATR-rank below which the market is treated as too dead to trade */
  deadVol: number
  /** ATR-rank above which volatility is treated as unsafe */
  wildVol: number
}

export const ENSEMBLE_DEFAULTS: EnsembleOptions = {
  activeFloor: 0.6,
  deadVol: 0.12,
  wildVol: 0.92,
}

export interface Blend {
  score: number
  gate: number
  gated: number
  agreement: number
}

export function blendVotes(
  votes: LimbVote[],
  atrRank: number | null,
  o: EnsembleOptions = ENSEMBLE_DEFAULTS,
): Blend {
  const totalWeight = votes.reduce((s, v) => s + v.weight, 0)
  if (totalWeight === 0) return { score: 0, gate: 0, gated: 0, agreement: 0 }

  let weighted = 0
  let activeWeight = 0
  for (const v of votes) {
    weighted += v.vote * v.weight
    if (Math.abs(v.vote) > 0.01) activeWeight += v.weight
  }
  const denom = Math.max(activeWeight, totalWeight * o.activeFloor)
  const score = Math.max(-1, Math.min(1, weighted / denom))

  // how much of the voting weight actually agrees with the blend's direction
  let agree = 0
  for (const v of votes) {
    if (Math.abs(v.vote) <= 0.01) continue
    if (Math.sign(v.vote) === Math.sign(score)) agree += v.weight * Math.abs(v.vote)
  }
  const engaged = votes.reduce((s, v) => s + (Math.abs(v.vote) > 0.01 ? v.weight * Math.abs(v.vote) : 0), 0)
  const agreement = engaged > 0 ? agree / engaged : 0

  const gate = volGate(atrRank, o) * (0.35 + 0.65 * agreement)
  return { score, gate, gated: score * gate, agreement }
}

/** Dead markets and blow-off markets are both bad places to size up. */
function volGate(atrRank: number | null, o: EnsembleOptions): number {
  if (atrRank === null) return 0
  if (atrRank < o.deadVol) return 0.25
  if (atrRank > o.wildVol) return 0.55
  // ramp in over the first slice above the dead zone
  const ramp = Math.min(1, (atrRank - o.deadVol) / 0.18)
  return 0.4 + 0.6 * ramp
}

/**
 * Score every bar. `detailFrom` is the first bar for which the full per-limb
 * breakdown is retained — keeping all of them for a 500-bar history is pure
 * memory churn when the UI only ever inspects the last handful.
 */
export function scoreBars(
  candles: Candle[],
  f: Features,
  detailFrom = candles.length - 1,
  limbs: Limb[] = LIMBS,
  o: EnsembleOptions = ENSEMBLE_DEFAULTS,
): ModelBar[] {
  const out: ModelBar[] = new Array(candles.length)
  for (let i = 0; i < candles.length; i++) {
    const votes = runLimbs(candles, f, i, limbs)
    const b = blendVotes(votes, f.atrPct[i], o)
    out[i] = {
      score: b.score,
      gated: b.gated,
      gate: b.gate,
      votes: i >= detailFrom ? votes : null,
    }
  }
  return out
}

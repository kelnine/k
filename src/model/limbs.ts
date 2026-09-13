import type { Candle } from '../data/types'
import type { Features } from './features'
import { activeZones } from './features'
import { ENTRY_ROLES, nearestLevel, po3Range, rangePosition } from './goldbach'
import type { LimbVote, Zone } from './types'

/**
 * The limbs of the Frankenstein model.
 *
 * Each limb is a small, self-contained opinion on direction: it sees the bar
 * index, the causal feature set, and nothing else — no limb knows what any
 * other limb thinks, and none of them can see past bar `i`. The ensemble in
 * `frankenstein.ts` stitches their votes together.
 *
 * A vote is -1 (max bearish) … +1 (max bullish). Returning 0 means "no read",
 * which is different from a weak read: it contributes nothing either way.
 */

export interface LimbContext {
  candles: Candle[]
  f: Features
  i: number
  /** zones visible and unmitigated at bar i */
  zones: Zone[]
}

export interface Limb {
  id: string
  name: string
  weight: number
  run(ctx: LimbContext): { vote: number; note: string }
}

const clamp = (v: number, lo = -1, hi = 1): number => Math.max(lo, Math.min(hi, v))

/** Smooth 1 → 0 decay over `halfLife` bars. */
const decay = (age: number, halfLife: number): number => Math.pow(0.5, age / halfLife)

// ---------------------------------------------------------------- limbs

const structureLimb: Limb = {
  id: 'structure',
  name: 'Market structure',
  weight: 1.6,
  run({ f, i }) {
    let last = null
    for (let k = f.events.length - 1; k >= 0; k--) {
      if (f.events[k].bar <= i) {
        last = f.events[k]
        break
      }
    }
    if (!last) return { vote: 0, note: 'no break yet' }
    const dir = last.side === 'bull' ? 1 : -1
    const strength = last.type === 'CHoCH' ? 1 : 0.8
    const age = i - last.bar
    const vote = dir * strength * (0.45 + 0.55 * decay(age, 30))
    return { vote: clamp(vote), note: `${last.type} ${last.side === 'bull' ? 'up' : 'down'} · ${age}b ago` }
  },
}

const orderBlockLimb: Limb = {
  id: 'orderblock',
  name: 'Order blocks',
  weight: 1.3,
  run({ candles, f, i, zones }) {
    const price = candles[i].close
    const atr = f.atr14[i] ?? 0
    if (atr === 0) return { vote: 0, note: 'warming up' }
    const obs = zones.filter((z) => z.kind === 'ob')
    if (obs.length === 0) return { vote: 0, note: 'none live' }

    let best: { z: Zone; d: number } | null = null
    for (const z of obs) {
      const d = price > z.top ? price - z.top : price < z.bottom ? z.bottom - price : 0
      if (!best || d < best.d) best = { z, d }
    }
    if (!best) return { vote: 0, note: 'none live' }
    const { z, d } = best
    // full weight while price is inside the block, fading out over one ATR
    const proximity = d === 0 ? 1 : Math.max(0, 1 - d / atr)
    if (proximity <= 0) return { vote: 0, note: `nearest ${(d / atr).toFixed(1)} ATR away` }
    const dir = z.side === 'bull' ? 1 : -1
    const where = d === 0 ? 'tagging' : 'approaching'
    return { vote: clamp(dir * proximity), note: `${where} ${z.side} OB` }
  },
}

const imbalanceLimb: Limb = {
  id: 'imbalance',
  name: 'Fair value gaps',
  weight: 0.9,
  run({ candles, i, zones }) {
    const price = candles[i].close
    const fvgs = zones.filter((z) => z.kind === 'fvg')
    if (fvgs.length === 0) return { vote: 0, note: 'balanced' }
    let inside: Zone | null = null
    let above = 0
    let below = 0
    for (const z of fvgs) {
      if (price <= z.top && price >= z.bottom) inside = z
      else if (z.bottom > price) above++
      else below++
    }
    if (inside) {
      const dir = inside.side === 'bull' ? 1 : -1
      return { vote: clamp(dir * 0.85), note: `inside ${inside.side} FVG` }
    }
    const total = above + below
    if (total === 0) return { vote: 0, note: 'balanced' }
    // unfilled gaps act as magnets: more above → upward draw
    const vote = ((above - below) / total) * 0.5
    return { vote: clamp(vote), note: `${above} above / ${below} below` }
  },
}

const trendLimb: Limb = {
  id: 'trend',
  name: 'Trend stack',
  weight: 1.2,
  run({ candles, f, i }) {
    const e21 = f.ema21[i]
    const e50 = f.ema50[i]
    const e200 = f.ema200[i]
    const price = candles[i].close
    if (e21 === null || e50 === null) return { vote: 0, note: 'warming up' }
    let vote = 0
    vote += price > e21 ? 0.3 : -0.3
    vote += e21 > e50 ? 0.35 : -0.35
    if (e200 !== null) vote += e50 > e200 ? 0.35 : -0.35
    else vote *= 1.3
    const label = vote > 0.5 ? 'stacked up' : vote < -0.5 ? 'stacked down' : 'mixed'
    return { vote: clamp(vote), note: label }
  },
}

const momentumLimb: Limb = {
  id: 'momentum',
  name: 'Momentum',
  weight: 1.0,
  run({ f, i }) {
    const r = f.rsi14[i]
    const h = f.macdHist[i]
    const hPrev = i > 0 ? f.macdHist[i - 1] : null
    if (r === null) return { vote: 0, note: 'warming up' }
    // RSI mapped so 50 is flat, 70/30 saturate
    const rsiVote = clamp((r - 50) / 20)
    let macdVote = 0
    if (h !== null && hPrev !== null) {
      const rising = h > hPrev
      macdVote = (h > 0 ? 0.5 : -0.5) + (rising ? 0.4 : -0.4)
    }
    const vote = clamp(rsiVote * 0.6 + clamp(macdVote) * 0.4)
    return { vote, note: `RSI ${r.toFixed(0)}${h !== null ? ` · MACD ${h > 0 ? '+' : '−'}` : ''}` }
  },
}

const vwapLimb: Limb = {
  id: 'vwap',
  name: 'VWAP',
  weight: 0.8,
  run({ candles, f, i }) {
    const v = f.vwap[i]
    const atr = f.atr14[i]
    if (v === null || !atr) return { vote: 0, note: 'warming up' }
    const dev = (candles[i].close - v) / atr
    // holding above VWAP is constructive; more than ~2.5 ATR out is stretched
    const vote = Math.abs(dev) > 2.5 ? clamp(-Math.sign(dev) * 0.4) : clamp(dev / 1.5)
    const label = Math.abs(dev) > 2.5 ? 'stretched' : dev >= 0 ? 'above' : 'below'
    return { vote, note: `${label} ${dev.toFixed(1)} ATR` }
  },
}

const liquidityLimb: Limb = {
  id: 'liquidity',
  name: 'Liquidity sweeps',
  weight: 1.1,
  run({ candles, f, i }) {
    const LOOKBACK = 8
    let vote = 0
    let note = 'no sweep'
    for (const pool of f.pools) {
      if (pool.swept === null || pool.swept > i || i - pool.swept > LOOKBACK) continue
      const c = candles[i]
      // a swept high that price closes back under is a bull trap → bearish
      const rejected = pool.side === 'high' ? c.close < pool.price : c.close > pool.price
      if (!rejected) continue
      const dir = pool.side === 'high' ? -1 : 1
      const fade = decay(i - pool.swept, LOOKBACK)
      if (Math.abs(dir * fade) > Math.abs(vote)) {
        vote = dir * fade
        note = `${pool.side === 'high' ? 'EQH' : 'EQL'} swept & rejected`
      }
    }
    return { vote: clamp(vote), note }
  },
}

const fibLimb: Limb = {
  id: 'fib',
  name: 'Fib pocket',
  weight: 0.9,
  run({ candles, f, i }) {
    let leg = null
    for (let k = f.legs.length - 1; k >= 0; k--) {
      if (f.legs[k].known <= i) {
        leg = f.legs[k]
        break
      }
    }
    if (!leg) return { vote: 0, note: 'no leg' }
    const span = leg.toPrice - leg.fromPrice
    if (span === 0) return { vote: 0, note: 'no leg' }
    const retrace = (leg.toPrice - candles[i].close) / span
    if (retrace < 0) {
      // price extended past the leg high/low — continuation, fading with distance
      return { vote: clamp((leg.side === 'bull' ? 1 : -1) * 0.3), note: 'in extension' }
    }
    if (retrace > 1.02) return { vote: 0, note: 'leg invalidated' }
    // the golden pocket: 0.618–0.786 back into the leg
    const inPocket = retrace >= 0.6 && retrace <= 0.79
    const dir = leg.side === 'bull' ? 1 : -1
    const vote = inPocket ? dir * 0.9 : retrace < 0.35 ? dir * 0.25 : 0
    return { vote: clamp(vote), note: `${(retrace * 100).toFixed(0)}% retrace${inPocket ? ' · pocket' : ''}` }
  },
}

const volumeLimb: Limb = {
  id: 'volume',
  name: 'Volume thrust',
  weight: 0.7,
  run({ candles, f, i }) {
    const avg = f.volAvg[i]
    if (!avg) return { vote: 0, note: 'warming up' }
    const c = candles[i]
    const rel = c.volume / avg
    if (rel < 1.2) return { vote: 0, note: `${rel.toFixed(1)}× avg` }
    const body = c.close - c.open
    const range = c.high - c.low || 1
    const conviction = clamp(body / range)
    const vote = clamp(conviction * Math.min(1, (rel - 1) / 1.5))
    return { vote, note: `${rel.toFixed(1)}× avg ${body >= 0 ? 'up' : 'down'} bar` }
  },
}

/**
 * Goldbach: where price sits in its power-of-three dealing range, and whether
 * it is sitting on a level the algorithm is expected to deal from.
 *
 * Discount is not a buy on its own — it is a buy *when structure is already
 * bullish*, and the vote only gets loud when price is actually tagging an
 * OB/FV/RB/LV level rather than floating between them. On the wrong side of
 * equilibrium for the prevailing structure it contributes a light lean, not a
 * fight: this limb is confluence, not a countertrend opinion.
 */
const goldbachLimb: Limb = {
  id: 'goldbach',
  name: 'Goldbach PO3',
  weight: 1.4,
  run({ candles, f, i }) {
    const price = candles[i].close
    const atr = f.atr14[i]
    const range = po3Range(price, f.po3)
    const pos = rangePosition(price, range)
    // +1 at the extreme discount, -1 at the extreme premium
    const lean = (0.5 - pos) * 2
    const level = nearestLevel(price, range, { roles: ENTRY_ROLES })
    const tagging = level !== null && atr !== null && Math.abs(level.price - price) <= atr * 0.35

    let bias = 0
    for (let k = f.events.length - 1; k >= 0; k--) {
      if (f.events[k].bar <= i) {
        bias = f.events[k].side === 'bull' ? 1 : -1
        break
      }
    }

    const withBias = bias !== 0 && Math.sign(lean) === bias
    const vote = clamp(lean * (withBias ? (tagging ? 1.6 : 0.8) : 0.3))
    const where = pos > 0.5 ? 'premium' : 'discount'
    const note = tagging
      ? `${level!.label.split(' | ')[0]} ${level!.role} · ${where}`
      : `${(pos * 100).toFixed(0)}% of ${f.po3} range`
    return { vote, note }
  },
}

export const LIMBS: Limb[] = [
  structureLimb,
  orderBlockLimb,
  imbalanceLimb,
  trendLimb,
  momentumLimb,
  vwapLimb,
  liquidityLimb,
  fibLimb,
  volumeLimb,
  goldbachLimb,
]

/** Run every limb at bar `i`. */
export function runLimbs(candles: Candle[], f: Features, i: number, limbs: Limb[] = LIMBS): LimbVote[] {
  const zones = activeZones(f.zones, i)
  const ctx: LimbContext = { candles, f, i, zones }
  return limbs.map((l) => {
    const { vote, note } = l.run(ctx)
    return { id: l.id, name: l.name, vote, weight: l.weight, note }
  })
}

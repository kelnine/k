import type { Candle } from '../data/types'
import { buildFeatures, type FeatureOptions } from './features'
import { scoreBars, ENSEMBLE_DEFAULTS, type EnsembleOptions } from './frankenstein'
import type {
  ClosedTrade,
  EquityPoint,
  ExitReason,
  LimbVote,
  ModelBar,
  ModelRun,
  Position,
  RunStats,
  Side,
} from './types'

/**
 * Paper execution for the Frankenstein ensemble.
 *
 * This is a simulator, not a broker: it fills its own orders against the
 * candles it is given. Nothing here places a real order anywhere.
 *
 * Fill discipline, so the equity curve means something:
 *   • a signal on bar i is filled at bar i+1's **open** — never at the close of
 *     the bar that produced it
 *   • stops and targets are checked against each later bar's high/low, and when
 *     a bar covers both, the stop is assumed to have hit first
 *   • partial exits bank R as they go; the runner trails behind the extreme
 */

export interface TraderOptions {
  /** |gated score| needed to open */
  enter: number
  /** |gated score| in the opposite direction that flips a position out */
  flip: number
  /** fraction of equity risked on a full-conviction trade */
  riskPct: number
  /** initial stop distance, in ATR */
  stopAtr: number
  /** R multiples at which to scale out, with the fraction taken at each */
  scaleOuts: { r: number; part: number }[]
  /** runner trail distance, in ATR, from the position's best close */
  trailAtr: number
  /** move the stop to break-even once this R is banked */
  breakEvenR: number
  /** bars to sit out after a stop-out */
  cooldown: number
  startEquity: number
}

export const TRADER_DEFAULTS: TraderOptions = {
  enter: 0.34,
  flip: 0.3,
  riskPct: 0.0075,
  stopAtr: 1.3,
  scaleOuts: [
    { r: 1, part: 0.5 },
    { r: 2, part: 0.5 },
  ],
  trailAtr: 2,
  breakEvenR: 1,
  cooldown: 3,
  startEquity: 25_000,
}

export interface ModelOptions {
  features?: Partial<FeatureOptions>
  ensemble?: EnsembleOptions
  trader?: Partial<TraderOptions>
}

/** Round a raw size into something a human would actually type into a ticket. */
function roundQty(qty: number): number {
  if (qty >= 50) return Math.floor(qty)
  if (qty >= 10) return Math.floor(qty * 2) / 2
  if (qty >= 1) return Math.floor(qty * 10) / 10
  return Math.floor(qty * 1000) / 1000
}

function fmt(n: number): string {
  const d = n >= 1000 ? 2 : n >= 10 ? 3 : n >= 1 ? 4 : 6
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
}

export function runModel(candles: Candle[], symbol: string, opts: ModelOptions = {}): ModelRun {
  const t: TraderOptions = { ...TRADER_DEFAULTS, ...opts.trader }
  const f = buildFeatures(candles, opts.features)
  // keep the per-limb detail for the tail the UI actually inspects
  const bars = scoreBars(candles, f, Math.max(0, candles.length - 3), undefined, opts.ensemble ?? ENSEMBLE_DEFAULTS)

  const closed: ClosedTrade[] = []
  const equity: EquityPoint[] = []
  let cash = t.startEquity
  let open: Position | null = null
  let cooldownUntil = -1
  let seq = 0

  for (let i = 1; i < candles.length; i++) {
    const c = candles[i]
    const atr = f.atr14[i] ?? null

    // ---- manage the open position against this bar
    if (open) {
      manage(open, c, i, atr, t)
      cash += takeRealized(open)
      if (open.qty <= 0) {
        const done = finish(open, i, c.time)
        closed.push(done)
        if (done.reason === 'stop') cooldownUntil = i + t.cooldown
        open = null
      }
    }

    // ---- act on the *previous* bar's signal, filled at this bar's open
    const sig = bars[i - 1]
    const atrPrev = f.atr14[i - 1]
    if (sig && atrPrev) {
      const dir: Side | null = sig.gated >= t.enter ? 'bull' : sig.gated <= -t.enter ? 'bear' : null

      // opposite conviction closes the book before anything else
      if (open && dir && dir !== open.side && Math.abs(sig.gated) >= t.flip) {
        exit(open, c.open, open.qty, i, c.time, 'flip')
        cash += takeRealized(open)
        closed.push(finish(open, i, c.time))
        open = null
      }

      if (!open && dir && i > cooldownUntil) {
        const conviction = Math.min(1, Math.abs(sig.gated))
        const entry: number = c.open
        const stopDist = atrPrev * t.stopAtr
        const stop: number = dir === 'bull' ? entry - stopDist : entry + stopDist
        // risk scales with conviction, from half size at threshold to full size at 1.0
        const risk = cash * t.riskPct * (0.5 + 0.5 * conviction)
        const qty = roundQty(risk / stopDist)
        if (qty > 0) {
          const sign: number = dir === 'bull' ? 1 : -1
          const pos: Position = {
            id: `${symbol}-${++seq}`,
            symbol,
            side: dir,
            bar: i,
            time: c.time,
            entry,
            stop,
            initialStop: stop,
            targets: t.scaleOuts.map((s) => entry + sign * s.r * stopDist),
            qty,
            initialQty: qty,
            risk: stopDist,
            conviction,
            realized: 0,
            extreme: entry,
            votes: (bars[i - 1].votes ?? []) as LimbVote[],
            fills: [
              {
                bar: i,
                time: c.time,
                price: entry,
                qty,
                action: dir === 'bull' ? 'buy' : 'sell',
                label: `${qty} @ ${fmt(entry)}`,
              },
            ],
          }
          open = pos
        }
      }
    }

    equity.push({ bar: i, time: c.time, equity: cash + unrealized(open, c.close) })
  }

  return {
    candles,
    bars,
    zones: f.zones,
    events: f.events,
    legs: f.legs,
    open,
    closed,
    equity,
    stats: summarise(closed, equity, t.startEquity),
    votes: bars[candles.length - 1]?.votes ?? [],
    startEquity: t.startEquity,
  }
}

// ---------------------------------------------------------------- position ops

function manage(p: Position, c: Candle, i: number, atr: number | null, t: TraderOptions): void {
  const bull = p.side === 'bull'
  const sign = bull ? 1 : -1

  // stop first: when a bar spans both stop and target, assume the worse fill
  if (bull ? c.low <= p.stop : c.high >= p.stop) {
    exit(p, p.stop, p.qty, i, c.time, p.stop === p.initialStop ? 'stop' : 'trail')
    return
  }

  for (let k = 0; k < p.targets.length; k++) {
    const target = p.targets[k]
    const hit = bull ? c.high >= target : c.low <= target
    if (!hit) continue
    const taken = p.fills.some((f) => f.label.startsWith(`T${k + 1}`))
    if (taken) continue
    // the last target takes whatever is left — otherwise rounding can strand a
    // dust position that never closes and blocks every later signal
    const last = k === p.targets.length - 1
    const qty = last ? p.qty : roundQty(p.initialQty * t.scaleOuts[k].part)
    exit(p, target, Math.min(qty, p.qty), i, c.time, 'target', `T${k + 1}`)
    if (p.qty <= 0) return
    if (t.scaleOuts[k].r >= t.breakEvenR) p.stop = p.entry
  }

  // trail the runner behind the best close once the first target is banked
  p.extreme = bull ? Math.max(p.extreme, c.close) : Math.min(p.extreme, c.close)
  if (atr && p.realized !== 0) {
    const trail = p.extreme - sign * atr * t.trailAtr
    p.stop = bull ? Math.max(p.stop, trail) : Math.min(p.stop, trail)
  }
}

function exit(
  p: Position,
  price: number,
  size: number,
  bar: number,
  time: number,
  reason: ExitReason,
  tag?: string,
): void {
  if (size <= 0) return
  // sweep a dust remainder out with the current fill rather than leaving it open
  const remainder = roundQty(p.qty - size)
  const qty = remainder > 0 && remainder < p.initialQty * 0.05 ? p.qty : size
  const sign = p.side === 'bull' ? 1 : -1
  p.realized += (price - p.entry) * qty * sign
  p.qty = Math.max(0, roundQty(p.qty - qty))
  const label = `${tag ? `${tag} ` : ''}${qty} @ ${fmt(price)}`
  p.fills.push({ bar, time, price, qty, action: p.side === 'bull' ? 'sell' : 'buy', label })
  p.lastReason = reason
}

/** Move newly realized PnL out of the position and into cash exactly once. */
function takeRealized(p: Position): number {
  const banked = p.realized - (p.banked ?? 0)
  p.banked = p.realized
  return banked
}

function finish(p: Position, bar: number, time: number): ClosedTrade {
  const last = p.fills[p.fills.length - 1]
  const r = p.risk * p.initialQty === 0 ? 0 : p.realized / (p.risk * p.initialQty)
  return {
    ...p,
    exitBar: bar,
    exitTime: time,
    exitPrice: last.price,
    reason: p.lastReason ?? 'target',
    pnl: p.realized,
    r,
  }
}

function unrealized(p: Position | null, price: number): number {
  if (!p || p.qty <= 0) return 0
  return (price - p.entry) * p.qty * (p.side === 'bull' ? 1 : -1)
}

// ---------------------------------------------------------------- stats

function summarise(closed: ClosedTrade[], equity: EquityPoint[], start: number): RunStats {
  let wins = 0
  let losses = 0
  let gross = 0
  let loss = 0
  let totalR = 0
  let pnl = 0
  for (const t of closed) {
    pnl += t.pnl
    totalR += t.r
    if (t.pnl >= 0) {
      wins++
      gross += t.pnl
    } else {
      losses++
      loss += -t.pnl
    }
  }
  let peak = start
  let maxDd = 0
  for (const e of equity) {
    peak = Math.max(peak, e.equity)
    maxDd = Math.max(maxDd, (peak - e.equity) / peak)
  }
  const last = equity[equity.length - 1]?.equity ?? start
  return {
    trades: closed.length,
    wins,
    losses,
    winRate: closed.length ? wins / closed.length : 0,
    expectancyR: closed.length ? totalR / closed.length : 0,
    profitFactor: loss > 0 ? gross / loss : gross > 0 ? Infinity : 0,
    totalR,
    pnl,
    maxDrawdown: maxDd,
    returnPct: ((last - start) / start) * 100,
  }
}

export type { ModelBar }

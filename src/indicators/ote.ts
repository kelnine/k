import type { Candle } from '../data/types'
import type { IndicatorDef, IndicatorResult, IndicatorShape } from './index'

/**
 * OTE Sniper — Fair Value Gap + Fibonacci OTE setup finder.
 *
 * The KCharts port of `pine/ote-sniper.pine`; both implement the same rules so
 * a zone drawn here matches the TradingView overlay bar for bar.
 *
 *   1. find the last confirmed impulse leg from swing pivots
 *   2. anchor a fib with 0 at the leg's terminal extreme and 1 at its origin,
 *      giving the 0.62 / 0.705 / 0.79 OTE band
 *   3. find an unfilled 3-candle FVG created inside that leg which overlaps the
 *      OTE band — the overlap is the entry zone
 *   4. project entry / stop / target, then track the setup through
 *      tapped -> target hit or stopped out
 *
 * A bearish leg (high -> low) is a short setup: price retraces *up* into the
 * zone. A bullish leg (low -> high) is a long setup.
 */

export interface OteOptions {
  /** fractal strength: bars required on each side of a swing pivot */
  swing: number
  /** ignore impulse legs smaller than this multiple of ATR(14) */
  minLegAtr: number
  /** shallow / entry / deep OTE retracement levels */
  oteA: number
  oteMid: number
  oteB: number
  /** only flag setups where an unfilled FVG overlaps the OTE band */
  requireFvg: boolean
  /** the FVG must have formed inside the impulse leg */
  fvgInLeg: boolean
  /** ignore FVGs thinner than this multiple of ATR(14) */
  minFvgAtr: number
  /** stop is pushed this far beyond the leg origin, in ATR(14) */
  stopBufAtr: number
  /** target fib level — 0 is the leg's terminal extreme, negatives extend past it */
  targetFib: number
  /** keep at most this many setups on the chart */
  maxSetups: number
  /** how resolved setups are drawn: dimmed zone, zone + result text, or nothing */
  history: 'faded' | 'labelled' | 'hide'
  longs: boolean
  shorts: boolean
}

const DEFAULTS: OteOptions = {
  swing: 5,
  minLegAtr: 2,
  oteA: 0.62,
  oteMid: 0.705,
  oteB: 0.79,
  requireFvg: true,
  fvgInLeg: true,
  minFvgAtr: 0.1,
  stopBufAtr: 0.25,
  targetFib: 0,
  maxSetups: 3,
  history: 'faded',
  longs: true,
  shorts: true,
}

const C = {
  bull: '38,166,154',
  bear: '239,83,80',
  fvg: '22,122,122',
  fib: '239,83,80',
  muted: 'rgba(139,147,163,0.85)',
}

type State = 'pending' | 'zone' | 'target' | 'stopped' | 'expired'

interface Gap {
  dir: 1 | -1
  top: number
  bot: number
  /** first candle of the 3-candle pattern (box anchor) */
  bar: number
  /** third candle — the bar the gap is confirmed on */
  born: number
  /** index price traded fully through it, or null while unfilled */
  filledAt: number | null
}

interface Setup {
  dir: 1 | -1
  origBar: number
  orig: number
  termBar: number
  term: number
  zoneTop: number
  zoneBot: number
  entry: number
  stop: number
  target: number
  rr: number
  gap: Gap | null
  state: State
  bornBar: number
  entryBar: number
  endBar: number
}

export function makeOte(opts: Partial<OteOptions> = {}): IndicatorDef {
  const o: OteOptions = { ...DEFAULTS, ...opts }
  return {
    id: 'ote',
    name: 'OTE Sniper',
    kind: 'overlay',
    compute: (candles) => compute(candles, o),
  }
}

const fibAt = (term: number, orig: number, v: number): number => term + v * (orig - term)

function atr14(candles: Candle[]): number[] {
  const n = candles.length
  const out = new Array<number>(n).fill(0)
  let sum = 0
  for (let i = 0; i < n; i++) {
    sum += trOf(candles, i)
    if (i >= 14) sum -= trOf(candles, i - 14)
    out[i] = sum / Math.min(i + 1, 14)
  }
  return out
}

function trOf(candles: Candle[], i: number): number {
  const prev = i > 0 ? candles[i - 1].close : candles[i].open
  return Math.max(
    candles[i].high - candles[i].low,
    Math.abs(candles[i].high - prev),
    Math.abs(candles[i].low - prev),
  )
}

interface Pivot {
  idx: number
  price: number
  confirm: number
  kind: 'H' | 'L'
}

function detectPivots(candles: Candle[], L: number): Pivot[] {
  const n = candles.length
  const out: Pivot[] = []
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
    if (isHigh) out.push({ idx: i, price: candles[i].high, confirm: i + L, kind: 'H' })
    if (isLow) out.push({ idx: i, price: candles[i].low, confirm: i + L, kind: 'L' })
  }
  return out
}

/** every 3-candle imbalance, with the bar that finally filled it */
function detectGaps(candles: Candle[], atr: number[], minAtr: number): Gap[] {
  const n = candles.length
  const gaps: Gap[] = []
  const SCAN = 500
  for (let i = 2; i < n; i++) {
    const a = candles[i - 2]
    const c = candles[i]
    let g: Gap | null = null
    if (c.low > a.high && c.low - a.high >= minAtr * atr[i]) {
      g = { dir: 1, top: c.low, bot: a.high, bar: i - 2, born: i, filledAt: null }
    } else if (c.high < a.low && a.low - c.high >= minAtr * atr[i]) {
      g = { dir: -1, top: a.low, bot: c.high, bar: i - 2, born: i, filledAt: null }
    }
    if (!g) continue
    for (let m = i + 1; m < Math.min(n, i + 1 + SCAN); m++) {
      if (g.dir === 1 ? candles[m].low < g.bot : candles[m].high > g.top) {
        g.filledAt = m
        break
      }
    }
    gaps.push(g)
  }
  return gaps
}

function compute(candles: Candle[], o: OteOptions): IndicatorResult {
  const n = candles.length
  if (n < o.swing * 2 + 5) {
    return { plots: [], shapes: [], legend: [{ color: C.muted, value: 'OTE —' }] }
  }

  const atr = atr14(candles)
  const pivots = detectPivots(candles, o.swing)
  const gaps = detectGaps(candles, atr, o.minFvgAtr)

  const confirmAt: Pivot[][] = Array.from({ length: n }, () => [])
  for (const p of pivots) if (p.confirm < n) confirmAt[p.confirm].push(p)

  const setups: Setup[] = []
  let lastH: Pivot | null = null
  let lastL: Pivot | null = null
  let reason = 'no impulse leg yet'
  let lastLegBar: number | null = null

  for (let t = 0; t < n; t++) {
    // ---- a newly confirmed pivot may complete an impulse leg
    for (const p of confirmAt[t]) {
      let leg: { dir: 1 | -1; origBar: number; orig: number; termBar: number; term: number } | null = null
      if (p.kind === 'L') {
        if (o.shorts && lastH && lastH.idx < p.idx && lastH.price > p.price) {
          leg = { dir: -1, origBar: lastH.idx, orig: lastH.price, termBar: p.idx, term: p.price }
        }
        lastL = p
      } else {
        if (o.longs && lastL && lastL.idx < p.idx && p.price > lastL.price) {
          leg = { dir: 1, origBar: lastL.idx, orig: lastL.price, termBar: p.idx, term: p.price }
        }
        lastH = p
      }
      if (leg) {
        lastLegBar = t
        const built = buildSetup(leg, t, candles, atr, gaps, o)
        if ('setup' in built) {
          reason = ''
          // a fresh leg supersedes anything still waiting to trigger
          for (const prev of setups) {
            if (prev.state === 'pending') {
              prev.state = 'expired'
              prev.endBar = t
            }
          }
          setups.push(built.setup)
        } else {
          reason = built.reason
        }
      }
    }

    // ---- advance open setups on this candle
    const c = candles[t]
    for (const s of setups) {
      if (s.state === 'pending') {
        const tapped = s.dir === -1 ? c.high >= s.zoneBot : c.low <= s.zoneTop
        if (tapped) {
          s.state = 'zone'
          s.entryBar = t
        } else if (s.dir === -1 ? c.low < s.term : c.high > s.term) {
          s.state = 'expired' // leg extended — the fib is stale
          s.endBar = t
        }
      }
      if (s.state === 'zone') {
        if (s.dir === -1 ? c.high >= s.stop : c.low <= s.stop) {
          s.state = 'stopped'
          s.endBar = t
        } else if (s.dir === -1 ? c.low <= s.target : c.high >= s.target) {
          s.state = 'target'
          s.endBar = t
        }
      }
    }
  }

  return render(setups.slice(-o.maxSetups), o, { reason, lastLegBar, bars: n })
}

/** Either a setup, or the gate that rejected this leg — surfaced in the legend. */
type Built = { setup: Setup } | { reason: string }

function buildSetup(
  leg: { dir: 1 | -1; origBar: number; orig: number; termBar: number; term: number },
  t: number,
  candles: Candle[],
  atr: number[],
  gaps: Gap[],
  o: OteOptions,
): Built {
  const legSize = Math.abs(leg.orig - leg.term)
  if (legSize <= 0 || legSize < o.minLegAtr * atr[t]) {
    const mult = atr[t] > 0 ? (legSize / atr[t]).toFixed(1) : '0'
    return { reason: `leg only ${mult}x ATR (needs ${o.minLegAtr}x)` }
  }

  const lvlA = fibAt(leg.term, leg.orig, o.oteA)
  const lvlB = fibAt(leg.term, leg.orig, o.oteB)
  const oteTop = Math.max(lvlA, lvlB)
  const oteBot = Math.min(lvlA, lvlB)

  // best unfilled gap overlapping the OTE band, on the side price must retrace to
  let best: Gap | null = null
  let bestOv = 0
  for (const g of gaps) {
    if (g.dir !== leg.dir) continue
    if (g.born > t) continue
    if (g.filledAt !== null && g.filledAt <= t) continue
    if (o.fvgInLeg && !(g.bar >= leg.origBar - 2 && g.bar <= leg.termBar + 2)) continue
    const ov = Math.min(g.top, oteTop) - Math.max(g.bot, oteBot)
    if (ov > bestOv) {
      bestOv = ov
      best = g
    }
  }
  if (!best && o.requireFvg) return { reason: 'no unfilled FVG in the OTE band' }

  const zoneTop = best ? Math.min(oteTop, best.top) : oteTop
  const zoneBot = best ? Math.max(oteBot, best.bot) : oteBot
  if (zoneTop <= zoneBot) return { reason: 'FVG and OTE band do not overlap' }

  // premise is gone if price already retraced clean through the zone
  const close = candles[t].close
  if (leg.dir === -1 ? close > zoneTop : close < zoneBot)
    return { reason: 'price already retraced through the zone' }

  const entry = Math.min(Math.max(fibAt(leg.term, leg.orig, o.oteMid), zoneBot), zoneTop)
  const stop = leg.orig - leg.dir * o.stopBufAtr * atr[t]
  const risk = Math.abs(entry - stop)
  const target = fibAt(leg.term, leg.orig, o.targetFib)
  if (risk <= 0) return { reason: 'stop sits on the entry' }
  if (leg.dir === -1 ? target >= entry : target <= entry)
    return { reason: 'target is not beyond entry' }

  const setup: Setup = {
    ...leg,
    zoneTop,
    zoneBot,
    entry,
    stop,
    target,
    rr: Math.abs(target - entry) / risk,
    gap: best,
    state: 'pending',
    bornBar: t,
    entryBar: t,
    endBar: t,
  }
  return { setup }
}

const LIVE: State[] = ['pending', 'zone']

/** Short enough to sit inside the zone box without colliding with anything. */
function statusText(s: Setup): string {
  const side = s.dir === 1 ? 'LONG' : 'SHORT'
  const move = (Math.abs(s.target - s.entry) / s.entry) * 100
  switch (s.state) {
    case 'pending':
      return `${side} · ${s.rr.toFixed(1)}R`
    case 'zone':
      return `${side} · IN ZONE · ${s.rr.toFixed(1)}R`
    case 'target':
      return `TARGET +${move.toFixed(2)}%`
    case 'stopped':
      return 'STOPPED'
    default:
      return 'EXPIRED'
  }
}

function render(
  setups: Setup[],
  o: OteOptions,
  diag: { reason: string; lastLegBar: number | null; bars: number },
): IndicatorResult {
  const shapes: IndicatorShape[] = []
  let live: Setup | null = null

  // Only a live setup gets the full treatment. Once it resolves the FVG box and
  // the projection come off the chart and just the zone stays, colour-coded by
  // outcome — otherwise a session's worth of setups stacks into unreadable soup.
  for (const s of setups) {
    const isLive = LIVE.includes(s.state)
    if (!isLive && o.history === 'hide') continue
    const detail = isLive || o.history === 'labelled'
    const x2 = isLive ? null : s.endBar
    const side = s.dir === 1 ? C.bull : C.bear
    const col =
      s.state === 'target' ? C.bull : s.state === 'stopped' ? C.bear : s.state === 'expired' ? '139,147,163' : side

    if (s.gap && detail) {
      shapes.push({
        type: 'box',
        x1: s.gap.bar,
        x2,
        yTop: s.gap.top,
        yBottom: s.gap.bot,
        fill: `rgba(${C.fvg},0.24)`,
        stroke: `rgba(${C.fvg},0.75)`,
        label: 'FVG',
        labelColor: `rgba(${C.fvg},0.95)`,
      })
    }

    shapes.push({
      type: 'box',
      x1: s.termBar,
      x2,
      yTop: s.zoneTop,
      yBottom: s.zoneBot,
      fill: `rgba(${col},${detail ? 0.28 : 0.07})`,
      stroke: `rgba(${col},${detail ? 0.95 : 0.35})`,
      label: detail ? statusText(s) : undefined,
      labelColor: `rgba(${col},0.95)`,
    })

    if (isLive) {
      const lx = s.state === 'pending' ? s.bornBar : s.entryBar
      shapes.push({
        type: 'box',
        x1: lx,
        x2,
        yTop: Math.max(s.entry, s.stop),
        yBottom: Math.min(s.entry, s.stop),
        fill: `rgba(${C.bear},0.12)`,
        label: `STOP ${fmt(s.stop)}`,
        labelColor: `rgba(${C.bear},0.8)`,
      })
      shapes.push({
        type: 'box',
        x1: lx,
        x2,
        yTop: Math.max(s.entry, s.target),
        yBottom: Math.min(s.entry, s.target),
        fill: `rgba(${C.bull},0.12)`,
        label: `TP ${fmt(s.target)} · ${((Math.abs(s.target - s.entry) / s.entry) * 100).toFixed(1)}%`,
        labelColor: `rgba(${C.bull},0.8)`,
      })
      shapes.push({
        type: 'line',
        x1: lx,
        x2,
        y1: s.entry,
        y2: s.entry,
        color: `rgba(${col},0.9)`,
        dash: [4, 3],
        label: `ENTRY ${fmt(s.entry)}`,
        labelColor: `rgba(${col},0.95)`,
      })
    }

    if (isLive) live = s
  }

  // fib ladder for the newest live setup only — overlapping ladders are noise
  if (live) {
    const near = Math.abs(live.entry - live.stop) * 0.15
    for (const v of [0, o.oteA, o.oteMid, o.oteB, 1]) {
      const p = fibAt(live.term, live.orig, v)
      const edge = v === 0 || v === 1
      // the projection already prints these two: the target sits on fib 0 and
      // the stop one buffer off fib 1, so the labels would stack
      const clash = Math.abs(p - live.target) < near || Math.abs(p - live.stop) < near
      shapes.push({
        type: 'line',
        x1: live.termBar,
        x2: null,
        y1: p,
        y2: p,
        color: `rgba(${C.fib},${edge ? 0.5 : 0.95})`,
        dash: edge ? [6, 4] : undefined,
        label: clash ? undefined : `${v} (${fmt(p)})`,
        labelColor: `rgba(${C.fib},${edge ? 0.7 : 1})`,
      })
    }
  }

  const legend = live
    ? [
        {
          color: `rgba(${live.dir === 1 ? C.bull : C.bear},1)`,
          value: `${live.dir === 1 ? 'LONG' : 'SHORT'} ${fmt(live.zoneBot)}–${fmt(live.zoneTop)} · ${live.rr.toFixed(1)}R`,
        },
        {
          color: C.muted,
          value: live.state === 'pending' ? 'waiting for retrace' : 'in zone',
        },
      ]
    : [
        { color: C.muted, value: 'no live setup' },
        { color: C.muted, value: diag.reason === '' ? 'last setup resolved' : diag.reason },
        {
          color: C.muted,
          value:
            diag.lastLegBar === null
              ? 'no leg yet'
              : `last leg ${diag.bars - 1 - diag.lastLegBar} bars ago`,
        },
      ]

  return { plots: [], shapes, legend }
}

function fmt(v: number): string {
  const abs = Math.abs(v)
  const dp = abs >= 1000 ? 1 : abs >= 1 ? 2 : 5
  return v.toFixed(dp)
}

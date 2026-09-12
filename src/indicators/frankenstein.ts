import type { Candle } from '../data/types'
import { runModel, traderOptions, getEntryStyle, type ModelRun, type Position, type Zone } from '../model'
import type { IndicatorDef, IndicatorResult, IndicatorShape } from './index'

/**
 * Chart rendering for the Frankenstein model.
 *
 * Two registry entries share one model run per candle set (see `modelFor`):
 *   • `frankenstein` — the overlay: live zones, the fib ladder off the last
 *     leg, a price-level heat ribbon in the right-hand gutter, and every
 *     simulated fill drawn as `qty @ price` with its risk/reward box
 *   • `frankscore`   — the pane: gated ensemble score with its entry thresholds
 *
 * Trades drawn here come from the paper simulator in `src/model/autotrader.ts`.
 * Nothing on this chart was executed at a broker.
 */

const C = {
  bull: '38,166,154',
  bear: '239,83,80',
  buy: '41,98,255',
  sell: '239,83,80',
  fib: '38,198,218',
  muted: 'rgba(139,147,163,0.8)',
}

// ---------------------------------------------------------------- model cache

const CACHE_MAX = 8
const cache = new Map<string, ModelRun>()

/**
 * One run per candle set, shared by the overlay and the score pane — and by
 * every chart in a multi-chart layout, which is why this is a small LRU rather
 * than a single slot.
 */
export function modelFor(candles: Candle[]): ModelRun | null {
  if (candles.length < 60) return null
  const last = candles[candles.length - 1]
  const key = `${getEntryStyle()}:${candles.length}:${candles[0].time}:${last.time}:${last.close}:${last.volume}`
  const hit = cache.get(key)
  if (hit) {
    cache.delete(key)
    cache.set(key, hit)
    return hit
  }
  const run = runModel(candles, 'CHART', { trader: traderOptions() })
  cache.set(key, run)
  if (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value as string)
  return run
}

/** How much history the heat profile and the zone filter look back over. */
const HEAT_BARS = 220
const TRADES_DRAWN = 8

/** Plain 14-bar ATR — used only to decide what is close enough to draw. */
function atr14(candles: Candle[]): number {
  const from = Math.max(1, candles.length - 14)
  let sum = 0
  let count = 0
  for (let i = from; i < candles.length; i++) {
    const c = candles[i]
    const pc = candles[i - 1].close
    sum += Math.max(c.high - c.low, Math.abs(c.high - pc), Math.abs(c.low - pc))
    count++
  }
  return count ? sum / count : 0
}

/** Price band price has actually visited recently, padded a little. */
function recentBand(candles: Candle[]): [number, number] {
  const from = Math.max(0, candles.length - HEAT_BARS)
  let lo = Infinity
  let hi = -Infinity
  for (let i = from; i < candles.length; i++) {
    lo = Math.min(lo, candles[i].low)
    hi = Math.max(hi, candles[i].high)
  }
  if (!isFinite(lo) || hi <= lo) return [0, 0]
  const pad = (hi - lo) * 0.04
  return [lo - pad, hi + pad]
}

function fmt(n: number): string {
  const d = n >= 1000 ? 2 : n >= 10 ? 3 : n >= 1 ? 4 : 6
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
}

// ---------------------------------------------------------------- shape builders

/**
 * Unmitigated zones, the ones price can still react to. A zone more than four
 * ATR away is still technically live but price is nowhere near it, and drawing
 * every one of them just paints the top of the chart a flat colour.
 */
function zoneShapes(zones: Zone[], n: number, price: number, atr: number): IndicatorShape[] {
  const reach = atr * 4 || Infinity
  const live = zones.filter((z) => {
    if (z.until !== null && z.until <= n - 1) return false
    const gap = price > z.top ? price - z.top : price < z.bottom ? z.bottom - price : 0
    return gap <= reach
  })
  const out: IndicatorShape[] = []
  for (const z of live.slice(-16)) {
    const color = z.side === 'bull' ? C.bull : C.bear
    const ob = z.kind === 'ob'
    out.push({
      type: 'box',
      x1: z.from,
      x2: z.until,
      yTop: z.top,
      yBottom: z.bottom,
      fill: `rgba(${color},${ob ? 0.13 : 0.06})`,
      stroke: ob ? `rgba(${color},0.5)` : undefined,
      label: ob ? 'OB' : 'FVG',
      labelColor: `rgba(${color},0.9)`,
    })
  }
  return out
}

const FIBS = [0.236, 0.382, 0.5, 0.618, 0.705, 0.786, 1, 1.272, 1.618]

/** Retracement + extension ladder off the most recent confirmed leg. */
function fibShapes(run: ModelRun): IndicatorShape[] {
  const leg = run.legs[run.legs.length - 1]
  if (!leg) return []
  const span = leg.toPrice - leg.fromPrice
  if (span === 0) return []
  return FIBS.map((r) => {
    const price = leg.toPrice - span * r
    const pocket = r >= 0.6 && r <= 0.79
    const ext = r > 1
    return {
      type: 'line',
      x1: leg.to,
      x2: null,
      y1: price,
      y2: price,
      color: `rgba(${C.fib},${pocket ? 0.75 : ext ? 0.4 : 0.28})`,
      width: pocket ? 1.4 : 1,
      dash: ext ? [4, 4] : undefined,
      label: `${r.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')}${ext ? ' Ext' : ''}`,
      labelColor: `rgba(${C.fib},${pocket ? 0.95 : 0.6})`,
    }
  })
}

/**
 * Price-level heat in the right-hand gutter: where volume actually traded,
 * boosted by any live zone or liquidity pool sitting at that level. Above
 * price it reads as supply (warm), below as demand (cool) — the same way the
 * zones are coloured.
 */
function heatShapes(run: ModelRun, candles: Candle[], lo: number, hi: number): IndicatorShape[] {
  const n = candles.length
  const from = Math.max(0, n - HEAT_BARS)
  if (hi <= lo) return []

  const BUCKETS = 32
  const step = (hi - lo) / BUCKETS
  const heat = new Array(BUCKETS).fill(0)
  for (let i = from; i < n; i++) {
    const c = candles[i]
    const a = Math.max(0, Math.min(BUCKETS - 1, Math.floor((c.low - lo) / step)))
    const b = Math.max(0, Math.min(BUCKETS - 1, Math.floor((c.high - lo) / step)))
    const share = c.volume / (b - a + 1)
    for (let k = a; k <= b; k++) heat[k] += share
  }
  // live structure counts double — resting orders, not just past trade
  for (const z of run.zones) {
    if (z.until !== null && z.until <= n - 1) continue
    const a = Math.max(0, Math.min(BUCKETS - 1, Math.floor((z.bottom - lo) / step)))
    const b = Math.max(0, Math.min(BUCKETS - 1, Math.floor((z.top - lo) / step)))
    const boost = (z.kind === 'ob' ? 0.5 : 0.25) * Math.max(...heat)
    for (let k = a; k <= b; k++) heat[k] += boost
  }

  const max = Math.max(...heat) || 1
  const price = candles[n - 1].close
  const out: IndicatorShape[] = []
  for (let k = 0; k < BUCKETS; k++) {
    const v = heat[k] / max
    if (v < 0.06) continue
    const bottom = lo + step * k
    const top = bottom + step
    const above = bottom >= price
    out.push({
      // starts past the Goldbach premium/discount column, which owns n+1…n+3
      type: 'box',
      x1: n + 4,
      x2: null,
      yTop: top,
      yBottom: bottom,
      fill: `rgba(${above ? C.bear : C.bull},${(0.08 + 0.42 * v).toFixed(3)})`,
    })
  }
  return out
}

/** Every simulated fill, drawn the way a broker's chart draws them. */
function tradeShapes(run: ModelRun, n: number): IndicatorShape[] {
  const out: IndicatorShape[] = []

  for (const t of run.closed.slice(-TRADES_DRAWN)) {
    out.push(...positionShapes(t, t.exitBar))
    out.push({
      type: 'line',
      x1: t.bar,
      x2: t.exitBar,
      y1: t.entry,
      y2: t.entry,
      color: `rgba(${t.side === 'bull' ? C.buy : C.sell},0.55)`,
      dash: [3, 3],
    })
    const win = t.r >= 0
    out.push({
      type: 'marker',
      x: t.exitBar,
      y: t.exitPrice,
      text: `${t.r >= 0 ? '+' : ''}${t.r.toFixed(2)}R`,
      color: `rgba(${win ? C.bull : C.bear},0.95)`,
      place: t.side === 'bull' ? 'below' : 'above',
    })
  }

  const open = run.open
  if (open) {
    out.push(...positionShapes(open, null))
    out.push({
      type: 'line',
      x1: open.bar,
      x2: null,
      y1: open.entry,
      y2: open.entry,
      color: `rgba(${open.side === 'bull' ? C.buy : C.sell},0.9)`,
      label: `ENTRY ${fmt(open.entry)}`,
      labelColor: `rgba(${open.side === 'bull' ? C.buy : C.sell},1)`,
    })
    out.push({
      type: 'line',
      x1: open.bar,
      x2: null,
      y1: open.stop,
      y2: open.stop,
      color: `rgba(${C.bear},0.85)`,
      dash: [5, 3],
      label: `STOP ${fmt(open.stop)}`,
      labelColor: `rgba(${C.bear},1)`,
    })
    open.targets.forEach((tp, i) => {
      out.push({
        type: 'line',
        x1: open.bar,
        x2: null,
        y1: tp,
        y2: tp,
        color: `rgba(${C.bull},0.7)`,
        dash: [5, 3],
        label: `T${i + 1} ${fmt(tp)}`,
        labelColor: `rgba(${C.bull},0.95)`,
      })
    })
  }

  const order = run.pending
  if (order) {
    const buy = order.side === 'bull'
    out.push({
      type: 'line',
      x1: order.bar,
      x2: null,
      y1: order.price,
      y2: order.price,
      color: `rgba(${buy ? C.buy : C.sell},0.9)`,
      dash: [2, 2],
      label: `${order.qty} | ${buy ? 'Buy' : 'Sell'} Limit · ${order.level}`,
      labelColor: `rgba(${buy ? C.buy : C.sell},1)`,
    })
  }

  // fills last so their labels sit on top of the zones
  for (const t of [...run.closed.slice(-TRADES_DRAWN), ...(run.open ? [run.open] : [])]) {
    for (const f of t.fills) {
      if (f.bar > n - 1) continue
      const buy = f.action === 'buy'
      // partial exits get their tag only — the full ticket line on every
      // scale-out turns a busy chart into an unreadable one
      const partial = /^T\d/.test(f.label)
      out.push({
        type: 'marker',
        x: f.bar,
        y: f.price,
        text: `${buy ? '▲' : '▼'} ${partial ? f.label.split(' ')[0] : f.label}`,
        color: `rgba(${buy ? C.buy : C.sell},0.95)`,
        place: buy ? 'below' : 'above',
      })
    }
  }
  return out
}

/** Risk box below the entry, reward box above it (mirrored for shorts). */
function positionShapes(p: Position, exitBar: number | null): IndicatorShape[] {
  const target = p.targets[p.targets.length - 1] ?? p.entry
  return [
    {
      type: 'box',
      x1: p.bar,
      x2: exitBar,
      yTop: Math.max(p.entry, p.initialStop),
      yBottom: Math.min(p.entry, p.initialStop),
      fill: `rgba(${C.bear},0.09)`,
    },
    {
      type: 'box',
      x1: p.bar,
      x2: exitBar,
      yTop: Math.max(p.entry, target),
      yBottom: Math.min(p.entry, target),
      fill: `rgba(${C.bull},0.09)`,
    },
  ]
}

// ---------------------------------------------------------------- registry defs

export function makeFrankenstein(): IndicatorDef {
  return {
    id: 'frankenstein',
    name: 'Frankenstein AI',
    kind: 'overlay',
    compute(candles): IndicatorResult {
      const run = modelFor(candles)
      if (!run) return { plots: [], shapes: [], legend: [{ color: C.muted, value: 'warming up' }] }
      const n = candles.length
      const bar = run.bars[n - 1]
      const [lo, hi] = recentBand(candles)
      const price = candles[n - 1].close
      const shapes: IndicatorShape[] = [
        ...heatShapes(run, candles, lo, hi),
        ...zoneShapes(run.zones, n, price, atr14(candles)),
        ...fibShapes(run),
        ...tradeShapes(run, n),
      ]

      const dir = bar.gated >= 0.34 ? 'LONG' : bar.gated <= -0.34 ? 'SHORT' : 'FLAT'
      const dirColor =
        dir === 'LONG' ? `rgba(${C.bull},1)` : dir === 'SHORT' ? `rgba(${C.bear},1)` : C.muted
      const eq = run.equity[run.equity.length - 1]?.equity ?? run.startEquity
      const legend = [
        { color: dirColor, value: `${dir} ${bar.gated >= 0 ? '+' : ''}${bar.gated.toFixed(2)}` },
        { color: C.muted, value: `gate ${(bar.gate * 100).toFixed(0)}%` },
        {
          color: run.stats.returnPct >= 0 ? `rgba(${C.bull},1)` : `rgba(${C.bear},1)`,
          value: `${run.stats.trades} trades · ${run.stats.returnPct >= 0 ? '+' : ''}${run.stats.returnPct.toFixed(1)}% · eq ${fmt(eq)}`,
        },
      ]
      if (run.open) {
        legend.push({
          color: `rgba(${run.open.side === 'bull' ? C.buy : C.sell},1)`,
          value: `open ${run.open.side === 'bull' ? 'long' : 'short'} ${run.open.qty} @ ${fmt(run.open.entry)}`,
        })
      }
      return { plots: [], shapes, legend }
    },
  }
}

export function makeFrankScore(): IndicatorDef {
  return {
    id: 'frankscore',
    name: 'Frankenstein Score',
    kind: 'pane',
    compute(candles): IndicatorResult {
      const run = modelFor(candles)
      const gated = candles.map((_, i) => run?.bars[i]?.gated ?? null)
      const raw = candles.map((_, i) => run?.bars[i]?.score ?? null)
      return {
        plots: [
          { key: 'gated', color: `rgba(${C.buy},0.9)`, style: 'hist', values: gated },
          { key: 'raw', color: 'rgba(171,71,188,0.9)', style: 'line', values: raw, width: 1 },
        ],
        guides: [
          { value: 0.34, color: `rgba(${C.bull},0.4)` },
          { value: 0, color: 'rgba(255,255,255,0.15)' },
          { value: -0.34, color: `rgba(${C.bear},0.4)` },
        ],
        range: [-1, 1],
      }
    },
  }
}

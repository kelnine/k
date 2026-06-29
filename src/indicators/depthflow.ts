import type { Candle } from '../data/types'
import type { IndicatorDef, IndicatorResult, IndicatorShape } from './index'

/**
 * DepthFlow — a from-scratch order-flow / liquidity overlay.
 *
 * A clean-room take on the "MicroDOM-style liquidity & volume blocks" genre:
 * everything is derived from raw OHLCV with no third-party library.
 *
 *   • Volume blocks   — a volume-by-price profile over a trailing window; the
 *                       high-volume nodes are drawn as horizontal liquidity
 *                       bands (red above price = resting supply / sell-side,
 *                       green below = resting demand / buy-side), each labelled
 *                       with the volume traded at that level.
 *   • Spot dominance  — buy vs. sell volume split (close-location method),
 *                       aggregated over a short recent window and shown in the
 *                       legend as "B xx% · S yy%".
 *   • Sweeps          — liquidity grabs: a wick pierces a recent swing
 *                       high/low and the candle closes back inside (stop-hunt).
 *   • Displacement    — impulsive candles whose body dwarfs recent ATR, the
 *                       confirmation that follows a sweep.
 *
 * Emitted as `shapes` (boxes / markers) in (candle-index, price) space, which
 * the engine renders on the main pane, plus a `legend` dominance read-out.
 */

export interface DepthFlowOptions {
  /** trailing candles included in the volume profile */
  window: number
  /** price-resolution of the profile (number of horizontal bins) */
  bins: number
  /** how many high-volume liquidity blocks to draw */
  maxBlocks: number
  /** a bin counts as "high volume" above this fraction of the peak bin */
  nodeRatio: number
  /** recent candles used for the spot buy/sell dominance read-out */
  domWindow: number
  /** displacement: body must exceed this multiple of ATR */
  dispAtrMult: number
  /** ATR length for the displacement filter */
  atrLen: number
  /** fractal strength for swing detection (sweeps) */
  swing: number
  /** cap on sweep / displacement markers (most recent kept) */
  maxSignals: number
}

const DEFAULTS: DepthFlowOptions = {
  window: 300,
  bins: 120,
  maxBlocks: 8,
  nodeRatio: 0.55,
  domWindow: 60,
  dispAtrMult: 1.6,
  atrLen: 14,
  swing: 5,
  maxSignals: 24,
}

const C = {
  supply: '239,83,80', // red — resting supply above price
  demand: '38,166,154', // green — resting demand below price
  buy: 'rgba(38,166,154,1)',
  sell: 'rgba(239,83,80,1)',
  muted: 'rgba(139,147,163,0.9)',
}

export function makeDepthFlow(opts: Partial<DepthFlowOptions> = {}): IndicatorDef {
  const o: DepthFlowOptions = { ...DEFAULTS, ...opts }
  return {
    id: 'depthflow',
    name: 'DepthFlow',
    kind: 'overlay',
    compute: (candles) => compute(candles, o),
  }
}

/** close-location buy/sell split of a candle's volume */
function buySell(c: Candle): { buy: number; sell: number } {
  const range = c.high - c.low
  if (range <= 0 || c.volume <= 0) {
    // doji / no range — split by direction, fall back to even
    const up = c.close > c.open ? 1 : c.close < c.open ? 0 : 0.5
    return { buy: c.volume * up, sell: c.volume * (1 - up) }
  }
  const buyFrac = (c.close - c.low) / range
  return { buy: c.volume * buyFrac, sell: c.volume * (1 - buyFrac) }
}

function atr(candles: Candle[], n: number): number[] {
  const out = new Array(candles.length).fill(0)
  let prev = 0
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i]
    const tr =
      i === 0
        ? c.high - c.low
        : Math.max(
            c.high - c.low,
            Math.abs(c.high - candles[i - 1].close),
            Math.abs(c.low - candles[i - 1].close),
          )
    prev = i === 0 ? tr : (prev * (n - 1) + tr) / n
    out[i] = prev
  }
  return out
}

function fmtVol(v: number): string {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(2) + 'M'
  if (v >= 1_000) return (v / 1_000).toFixed(3) + 'K'
  return Math.round(v).toString()
}

interface Block {
  top: number
  bottom: number
  vol: number
  buy: number
  sell: number
}

function compute(candles: Candle[], o: DepthFlowOptions): IndicatorResult {
  const n = candles.length
  const shapes: IndicatorShape[] = []
  if (n < Math.max(o.atrLen, o.swing * 2 + 3) + 2) {
    return { plots: [], shapes, legend: [{ color: C.muted, value: '—' }] }
  }

  const start = Math.max(0, n - o.window)
  const last = candles[n - 1].close

  // ---- volume-by-price profile over the trailing window
  let lo = Infinity
  let hi = -Infinity
  for (let i = start; i < n; i++) {
    if (candles[i].low < lo) lo = candles[i].low
    if (candles[i].high > hi) hi = candles[i].high
  }
  const span = hi - lo
  if (span <= 0) return { plots: [], shapes, legend: [{ color: C.muted, value: '—' }] }

  const binSize = span / o.bins
  const volBin = new Array(o.bins).fill(0)
  const buyBin = new Array(o.bins).fill(0)
  const sellBin = new Array(o.bins).fill(0)

  for (let i = start; i < n; i++) {
    const c = candles[i]
    const { buy, sell } = buySell(c)
    // spread the candle's volume evenly across the bins it spans
    const b0 = Math.max(0, Math.floor((c.low - lo) / binSize))
    const b1 = Math.min(o.bins - 1, Math.floor((c.high - lo) / binSize))
    const k = b1 - b0 + 1
    const vEach = c.volume / k
    const buyEach = buy / k
    const sellEach = sell / k
    for (let b = b0; b <= b1; b++) {
      volBin[b] += vEach
      buyBin[b] += buyEach
      sellBin[b] += sellEach
    }
  }

  const peak = Math.max(...volBin)
  const threshold = peak * o.nodeRatio

  // ---- merge contiguous high-volume bins into liquidity blocks
  const blocks: Block[] = []
  let run: Block | null = null
  for (let b = 0; b < o.bins; b++) {
    if (volBin[b] >= threshold) {
      const top = lo + (b + 1) * binSize
      const bottom = lo + b * binSize
      if (run === null) {
        run = { top, bottom, vol: volBin[b], buy: buyBin[b], sell: sellBin[b] }
      } else {
        run.top = top
        run.vol += volBin[b]
        run.buy += buyBin[b]
        run.sell += sellBin[b]
      }
    } else if (run !== null) {
      blocks.push(run)
      run = null
    }
  }
  if (run !== null) blocks.push(run)

  // keep the heaviest blocks
  blocks.sort((a, b) => b.vol - a.vol)
  const top = blocks.slice(0, o.maxBlocks)

  for (const blk of top) {
    const center = (blk.top + blk.bottom) / 2
    const above = center >= last
    const rgb = above ? C.supply : C.demand
    const dom = blk.buy + blk.sell > 0 ? Math.round((blk.buy / (blk.buy + blk.sell)) * 100) : 50
    shapes.push({
      type: 'box',
      x1: start,
      x2: null,
      yTop: blk.top,
      yBottom: blk.bottom,
      fill: `rgba(${rgb},0.16)`,
      stroke: `rgba(${rgb},0.5)`,
      label: `${fmtVol(blk.vol)}  ·  B${dom}/S${100 - dom}`,
      labelColor: `rgba(${rgb},0.95)`,
      labelAlign: 'right',
    })
  }

  // ---- spot buy/sell dominance over a short recent window
  let recBuy = 0
  let recSell = 0
  for (let i = Math.max(0, n - o.domWindow); i < n; i++) {
    const { buy, sell } = buySell(candles[i])
    recBuy += buy
    recSell += sell
  }
  const recTot = recBuy + recSell
  const bPct = recTot > 0 ? Math.round((recBuy / recTot) * 100) : 50
  const sPct = 100 - bPct
  const domColor = bPct >= sPct ? C.buy : C.sell

  // ---- sweeps (liquidity grabs) + displacement, on the trailing window
  const a = atr(candles, o.atrLen)
  const markers: IndicatorShape[] = []
  const L = o.swing

  // last confirmed swing high / low as we walk forward
  let swingHigh: number | null = null
  let swingLow: number | null = null
  for (let i = start; i < n; i++) {
    // confirm the pivot that sits L bars back
    const p = i - L
    if (p - L >= 0 && p + L < n) {
      let isHigh = true
      let isLow = true
      for (let k = 1; k <= L; k++) {
        if (!(candles[p].high >= candles[p - k].high && candles[p].high >= candles[p + k].high)) isHigh = false
        if (!(candles[p].low <= candles[p - k].low && candles[p].low <= candles[p + k].low)) isLow = false
        if (!isHigh && !isLow) break
      }
      if (isHigh) swingHigh = candles[p].high
      if (isLow) swingLow = candles[p].low
    }

    const c = candles[i]
    // sell-side sweep: dip under a swing low, close back above it
    if (swingLow !== null && c.low < swingLow && c.close > swingLow) {
      markers.push({ type: 'marker', x: i, y: c.low, text: 'sweep', color: C.buy, place: 'below' })
      swingLow = null
    }
    // buy-side sweep: poke above a swing high, close back below it
    if (swingHigh !== null && c.high > swingHigh && c.close < swingHigh) {
      markers.push({ type: 'marker', x: i, y: c.high, text: 'sweep', color: C.sell, place: 'above' })
      swingHigh = null
    }

    // displacement: an impulsive body relative to ATR
    const body = Math.abs(c.close - c.open)
    if (a[i] > 0 && body > a[i] * o.dispAtrMult) {
      const up = c.close >= c.open
      markers.push({
        type: 'marker',
        x: i,
        y: up ? c.low : c.high,
        text: up ? 'DISP▲' : 'DISP▼',
        color: up ? C.buy : C.sell,
        place: up ? 'below' : 'above',
      })
    }
  }

  // blocks first (faint), signals on top
  shapes.push(...markers.slice(-o.maxSignals))

  return {
    plots: [],
    shapes,
    legend: [{ color: domColor, value: `B ${bPct}% · S ${sPct}%` }],
  }
}

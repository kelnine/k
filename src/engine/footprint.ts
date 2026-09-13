import type { Candle, Trade } from '../data/types'
import {
  applyTrade as foldTrade,
  finalizeBar,
  rowImbalances,
  seriesMetrics,
  type FootprintBar,
  type FootprintSeries,
} from '../data/orderflow'
import { imbalanceColor, inkFor, paramColor, paramInk } from './colorscale'
import { formatFullTime, formatPrice, formatTimeTick, niceTicks } from './utils'

/**
 * Footprint (orderflow) renderer.
 *
 * Every candle becomes a column of price rows; each row shows the volume that
 * traded into the bid and into the ask, tinted by the diagonal imbalance
 * between them, with a volume profile beside it and a parameters strip
 * (roc / volume / cum delta / delta) underneath.
 *
 * Same interaction model as the candle engine: drag to pan, wheel to zoom
 * anchored at the cursor, drag the price axis to stretch it, double-click to
 * reset.
 */

export interface HoveredLevel {
  price: number
  bid: number
  ask: number
  imbalance: number
}

export interface FootprintLegendData {
  bar: FootprintBar | null
  cumDelta: number | null
  roc: number | null
  level: HoveredLevel | null
  rowSize: number
  bars: number
  trades: number
}

export interface FootprintOptions {
  onLegend?(d: FootprintLegendData): void
}

const COLORS = {
  bg: '#0d1118',
  grid: 'rgba(255,255,255,0.045)',
  text: '#8b93a3',
  axisBg: '#0d1118',
  separator: 'rgba(255,255,255,0.12)',
  crosshair: 'rgba(170,178,196,0.6)',
  up: '#26a69a',
  down: '#ef5350',
  profile: 'rgba(124,77,255,0.85)',
  poc: 'rgba(255,205,86,0.9)',
}

const AXIS_W = 72
const TIME_AXIS_H = 26
const PARAM_ROWS = ['roc', 'volume', 'cum delta', 'delta'] as const
const PARAM_ROW_H = 15
const PARAM_PANE_H = PARAM_ROWS.length * PARAM_ROW_H + 8
const PARAM_LABEL_W = 62
const DEFAULT_COL_W = 86
const MIN_COL_W = 5
const MAX_COL_W = 360
const RIGHT_OFFSET_COLS = 1.5

interface Scale {
  top: number
  bottom: number
  min: number
  max: number
}

type Drag =
  | { kind: 'pan'; lastX: number; lastY: number }
  | { kind: 'scale'; lastY: number }

/**
 * Cell label: at most four characters, so a bid/ask pair always fits the
 * width of one footprint row.
 */
export function formatCell(v: number): string {
  const a = Math.abs(v)
  if (a === 0) return '0'
  if (a >= 10_000) return (v / 1000).toFixed(0) + 'k'
  if (a >= 1000) return (v / 1000).toFixed(1) + 'k'
  if (a >= 10) return v.toFixed(0)
  if (a >= 1) return v.toFixed(1)
  if (a >= 0.01) return v.toFixed(2)
  return '~0'
}

/** Compact volume label for the legend and the parameters strip. */
export function formatSize(v: number): string {
  const a = Math.abs(v)
  if (a >= 100_000) return (v / 1000).toFixed(0) + 'k'
  if (a >= 10_000) return (v / 1000).toFixed(1) + 'k'
  if (a >= 100) return v.toFixed(0)
  if (a >= 10) return v.toFixed(1)
  if (a >= 1) return v.toFixed(2)
  if (a === 0) return '0'
  return v.toFixed(3)
}

export class FootprintEngine {
  private container: HTMLElement
  private main: HTMLCanvasElement
  private overlay: HTMLCanvasElement
  private opts: FootprintOptions
  private ro: ResizeObserver

  private series: FootprintSeries = {
    bars: [],
    rowSize: 1,
    cumDelta: [],
    roc: [],
    coverageFrom: 0,
    tradeCount: 0,
  }
  private byTime = new Map<number, FootprintBar>()
  private tfMs = 60_000
  private symbol = ''
  private showPoc = true

  private colW = DEFAULT_COL_W
  private rightIndex = 0
  private priceZoom = 1
  private priceAnchor: number | null = null
  private width = 0
  private height = 0
  private scale: Scale | null = null

  private mouse: { x: number; y: number } | null = null
  private drag: Drag | null = null
  private metricsDirty = false
  private rafId = 0
  private overlayRafId = 0
  private destroyed = false

  constructor(container: HTMLElement, opts: FootprintOptions = {}) {
    this.container = container
    this.opts = opts
    if (getComputedStyle(container).position === 'static') container.style.position = 'relative'
    container.style.overflow = 'hidden'
    this.main = document.createElement('canvas')
    this.overlay = document.createElement('canvas')
    for (const c of [this.main, this.overlay]) {
      c.style.position = 'absolute'
      c.style.inset = '0'
      container.appendChild(c)
    }
    this.overlay.style.cursor = 'crosshair'

    this.ro = new ResizeObserver(() => this.resize())
    this.ro.observe(container)
    this.resize()

    this.overlay.addEventListener('pointerdown', this.onPointerDown)
    this.overlay.addEventListener('pointermove', this.onPointerMove)
    this.overlay.addEventListener('pointerup', this.onPointerUp)
    this.overlay.addEventListener('pointerleave', this.onPointerLeave)
    this.overlay.addEventListener('wheel', this.onWheel, { passive: false })
    this.overlay.addEventListener('dblclick', this.resetView)
  }

  destroy(): void {
    this.destroyed = true
    this.ro.disconnect()
    cancelAnimationFrame(this.rafId)
    cancelAnimationFrame(this.overlayRafId)
    this.main.remove()
    this.overlay.remove()
  }

  // ------------------------------------------------------------- data

  setSeries(series: FootprintSeries, tfMs: number, symbol: string): void {
    this.series = series
    this.tfMs = tfMs
    this.symbol = symbol
    this.byTime = new Map(series.bars.map((b) => [b.time, b]))
    this.rightIndex = series.bars.length - 1 + RIGHT_OFFSET_COLS
    this.priceAnchor = null
    this.priceZoom = 1
    this.requestRender()
    this.emitLegend()
  }

  setShowPoc(v: boolean): void {
    this.showPoc = v
    this.requestRender()
  }

  /** Keep OHLC in step with the candle stream, and open a bar on a new bucket. */
  applyCandle(c: Candle): void {
    const bars = this.series.bars
    if (bars.length === 0) return
    const last = bars[bars.length - 1]
    if (c.time === last.time) {
      Object.assign(last, {
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        volume: c.volume,
      })
    } else if (c.time > last.time) {
      this.openBar(c)
    } else {
      return
    }
    this.requestRender()
  }

  /** Fold a live print into its bar, opening one first if the bucket rolled. */
  applyTrade(t: Trade): void {
    const bucket = Math.floor(t.time / this.tfMs) * this.tfMs
    let bar = this.byTime.get(bucket)
    if (!bar) {
      const bars = this.series.bars
      // only ever extend forward; late prints for evicted bars are dropped
      if (bars.length > 0 && bucket <= bars[bars.length - 1].time) return
      bar = this.openBar({
        time: bucket,
        open: t.price,
        high: t.price,
        low: t.price,
        close: t.price,
        volume: 0,
      })
    }
    foldTrade(bar, t, this.series.rowSize)
    bar.high = Math.max(bar.high, t.price)
    bar.low = Math.min(bar.low, t.price)
    bar.close = t.price
    bar.volume += t.qty
    finalizeBar(bar)
    this.metricsDirty = true
    this.requestRender()
  }

  private openBar(c: Candle): FootprintBar {
    const bars = this.series.bars
    const atRightEdge = this.rightIndex >= bars.length - 1
    const bar: FootprintBar = {
      ...c,
      levels: [],
      bidTotal: 0,
      askTotal: 0,
      delta: 0,
      flowVolume: 0,
      poc: c.close,
      trades: 0,
    }
    bars.push(bar)
    this.byTime.set(bar.time, bar)
    if (atRightEdge) this.rightIndex += 1
    this.metricsDirty = true
    return bar
  }

  resetView = (): void => {
    this.colW = DEFAULT_COL_W
    this.rightIndex = this.series.bars.length - 1 + RIGHT_OFFSET_COLS
    this.priceZoom = 1
    this.priceAnchor = null
    this.requestRender()
  }

  // ------------------------------------------------------------- geometry

  private get plotW(): number {
    return Math.max(0, this.width - AXIS_W)
  }

  private get paneBottom(): number {
    return Math.max(0, this.height - TIME_AXIS_H - PARAM_PANE_H)
  }

  private xForIndex(i: number): number {
    return this.plotW + (i - this.rightIndex) * this.colW
  }

  private indexForX(x: number): number {
    return this.rightIndex + (x - this.plotW) / this.colW
  }

  private yForPrice(p: number, s: Scale): number {
    const span = s.max - s.min || 1
    return s.top + ((s.max - p) / span) * (s.bottom - s.top)
  }

  private priceForY(y: number, s: Scale): number {
    const span = s.max - s.min || 1
    return s.max - ((y - s.top) / (s.bottom - s.top)) * span
  }

  private visibleRange(): [number, number] {
    const from = Math.max(0, Math.ceil(this.indexForX(0)) - 1)
    const to = Math.min(this.series.bars.length - 1, Math.floor(this.rightIndex))
    return [from, to]
  }

  private computeScale(from: number, to: number): Scale {
    const top = 8
    const bottom = Math.max(top + 10, this.paneBottom - 4)
    const { bars, rowSize } = this.series
    let min = Infinity
    let max = -Infinity
    for (let i = from; i <= to; i++) {
      const b = bars[i]
      if (!b) continue
      min = Math.min(min, b.low, b.levels[0]?.price ?? Infinity)
      max = Math.max(max, b.high, (b.levels[b.levels.length - 1]?.price ?? -Infinity) + rowSize)
    }
    if (!isFinite(min) || !isFinite(max)) {
      min = 0
      max = 1
    }
    const pad = Math.max(rowSize, (max - min) * 0.04)
    min -= pad
    max += pad
    const fitted = max - min || 1
    const span = fitted / this.priceZoom
    const center = this.priceAnchor ?? (min + max) / 2
    return { top, bottom, min: center - span / 2, max: center + span / 2 }
  }

  // ------------------------------------------------------------- rendering

  private resize(): void {
    const r = this.container.getBoundingClientRect()
    this.width = Math.floor(r.width)
    this.height = Math.floor(r.height)
    const dpr = window.devicePixelRatio || 1
    for (const c of [this.main, this.overlay]) {
      c.width = Math.max(1, this.width * dpr)
      c.height = Math.max(1, this.height * dpr)
      c.style.width = this.width + 'px'
      c.style.height = this.height + 'px'
    }
    this.requestRender()
  }

  private requestRender(): void {
    cancelAnimationFrame(this.rafId)
    this.rafId = requestAnimationFrame(() => {
      if (!this.destroyed) {
        this.render()
        this.renderOverlay()
      }
    })
  }

  private requestOverlayRender(): void {
    cancelAnimationFrame(this.overlayRafId)
    this.overlayRafId = requestAnimationFrame(() => {
      if (!this.destroyed) this.renderOverlay()
    })
  }

  private render(): void {
    const ctx = this.main.getContext('2d')
    if (!ctx || this.width === 0 || this.height === 0) return
    if (this.metricsDirty) {
      const m = seriesMetrics(this.series.bars)
      this.series.cumDelta = m.cumDelta
      this.series.roc = m.roc
      this.metricsDirty = false
    }
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = COLORS.bg
    ctx.fillRect(0, 0, this.width, this.height)

    const [from, to] = this.visibleRange()
    const hasData = this.series.bars.length > 0 && from <= to
    const s = this.computeScale(from, to)
    this.scale = s

    const ticks = this.computeTimeTicks(from, to)
    this.drawGrid(ctx, s, ticks)
    if (hasData) {
      this.drawWatermark(ctx, s)
      ctx.save()
      ctx.beginPath()
      ctx.rect(0, s.top - 6, this.plotW, s.bottom - s.top + 12)
      ctx.clip()
      for (let i = from; i <= to; i++) this.drawColumn(ctx, i, s)
      ctx.restore()
      this.drawParams(ctx, from, to)
    }
    this.drawPriceAxis(ctx, s)
    this.drawTimeAxis(ctx, ticks)
  }

  private computeTimeTicks(from: number, to: number): { i: number; t: number }[] {
    const bars = this.series.bars
    if (bars.length === 0 || from > to) return []
    const step = Math.max(1, Math.ceil(90 / this.colW))
    const out: { i: number; t: number }[] = []
    for (let i = Math.ceil(from / step) * step; i <= to; i += step) out.push({ i, t: bars[i].time })
    return out
  }

  private drawGrid(ctx: CanvasRenderingContext2D, s: Scale, ticks: { i: number }[]): void {
    ctx.strokeStyle = COLORS.grid
    ctx.lineWidth = 1
    ctx.beginPath()
    for (const tick of ticks) {
      const x = Math.round(this.xForIndex(tick.i) - this.colW / 2) + 0.5
      ctx.moveTo(x, 0)
      ctx.lineTo(x, this.paneBottom)
    }
    for (const v of niceTicks(s.min, s.max, Math.max(2, Math.floor((s.bottom - s.top) / 60)))) {
      const y = Math.round(this.yForPrice(v, s)) + 0.5
      ctx.moveTo(0, y)
      ctx.lineTo(this.plotW, y)
    }
    ctx.stroke()
    ctx.strokeStyle = COLORS.separator
    ctx.beginPath()
    ctx.moveTo(0, Math.round(this.paneBottom) + 0.5)
    ctx.lineTo(this.width, Math.round(this.paneBottom) + 0.5)
    ctx.stroke()
  }

  private drawWatermark(ctx: CanvasRenderingContext2D, s: Scale): void {
    ctx.save()
    ctx.fillStyle = 'rgba(255,255,255,0.035)'
    ctx.font = `700 ${Math.min(64, this.plotW / 9)}px system-ui, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(`${this.symbol} FOOTPRINT`, this.plotW / 2, (s.top + s.bottom) / 2)
    ctx.restore()
  }

  /** One candle: heat cells, bid/ask numbers, volume profile, candle overlay. */
  private drawColumn(ctx: CanvasRenderingContext2D, i: number, s: Scale): void {
    const bar = this.series.bars[i]
    if (!bar) return
    const rowSize = this.series.rowSize
    const xc = this.xForIndex(i)
    if (xc + this.colW < 0 || xc - this.colW > this.plotW) return

    const gap = Math.min(8, this.colW * 0.09)
    const inner = this.colW - gap
    // the profile gets a slim fixed-ish slice so the numbers keep the room
    const profW = bar.levels.length > 0 ? Math.max(3, Math.min(26, inner * 0.26)) : 0
    const cellW = Math.max(3, inner - profW)
    const cellL = xc - this.colW / 2 + gap / 2
    const cx = cellL + cellW / 2
    const rh = (rowSize / (s.max - s.min || 1)) * (s.bottom - s.top)

    if (bar.levels.length > 0 && rh >= 1.5) {
      const imb = rowImbalances(bar.levels)
      let maxRow = 0
      for (const l of bar.levels) maxRow = Math.max(maxRow, l.bid + l.ask)
      // a pair of 4-char labels plus a gap is ~10 monospace glyphs wide
      const fontPx = Math.floor(Math.min(11, rh * 0.8, cellW / 6))
      const showText = rh >= 8.5 && fontPx >= 8
      if (showText) {
        ctx.font = `${fontPx}px ui-monospace, SFMono-Regular, "Courier New", monospace`
        ctx.textBaseline = 'middle'
      }

      for (let r = 0; r < bar.levels.length; r++) {
        const l = bar.levels[r]
        const yTop = this.yForPrice(l.price + rowSize, s)
        if (yTop > s.bottom || yTop + rh < s.top) continue
        const h = Math.max(1, rh - (rh > 4 ? 1 : 0))
        const z = imb[r]
        ctx.fillStyle = imbalanceColor(z)
        ctx.fillRect(cellL, yTop, cellW, h)

        if (showText) {
          ctx.fillStyle = inkFor(z)
          ctx.textAlign = 'right'
          ctx.fillText(formatCell(l.bid), cx - 3, yTop + h / 2, cellW / 2 - 4)
          ctx.textAlign = 'left'
          ctx.fillText(formatCell(l.ask), cx + 4, yTop + h / 2, cellW / 2 - 4)
        }

        if (profW > 2 && maxRow > 0) {
          const w = ((l.bid + l.ask) / maxRow) * profW
          if (w > 0.5) {
            ctx.fillStyle = COLORS.profile
            ctx.fillRect(cellL + cellW + 1, yTop + h * 0.15, w, Math.max(1, h * 0.7))
          }
        }
      }

      if (this.showPoc && rh >= 3) {
        const y = this.yForPrice(bar.poc + rowSize, s)
        ctx.strokeStyle = COLORS.poc
        ctx.lineWidth = 1
        ctx.strokeRect(Math.round(cellL) + 0.5, Math.round(y) + 0.5, Math.round(cellW), Math.max(1, Math.round(rh - 1)))
      }
    }

    // candle drawn over the cells, as in the reference chart
    const up = bar.close >= bar.open
    const color = up ? COLORS.up : COLORS.down
    const yH = this.yForPrice(bar.high, s)
    const yL = this.yForPrice(bar.low, s)
    const yO = this.yForPrice(bar.open, s)
    const yC = this.yForPrice(bar.close, s)
    const bodyW = Math.max(2, Math.min(6, cellW * 0.18))
    ctx.globalAlpha = bar.levels.length > 0 ? 0.9 : 1
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.moveTo(cx, yH)
    ctx.lineTo(cx, yL)
    ctx.stroke()
    ctx.globalAlpha = bar.levels.length > 0 ? 0.45 : 1
    ctx.fillStyle = color
    ctx.fillRect(cx - bodyW / 2, Math.min(yO, yC), bodyW, Math.max(1, Math.abs(yC - yO)))
    ctx.globalAlpha = 1
    ctx.lineWidth = 1
  }

  /** The roc / volume / cum delta / delta strip under the chart. */
  private drawParams(ctx: CanvasRenderingContext2D, from: number, to: number): void {
    const top = this.paneBottom
    const { bars, cumDelta, roc } = this.series
    const showText = this.colW >= 34
    ctx.font = '10px system-ui, sans-serif'
    ctx.textBaseline = 'middle'

    for (let i = from; i <= to; i++) {
      const bar = bars[i]
      const xc = this.xForIndex(i)
      const w = Math.max(1, this.colW - 3)
      const x = xc - this.colW / 2 + 1.5
      if (x + w < 0 || x > this.plotW) continue
      const values: (number | null)[] = [roc[i] ?? null, bar.flowVolume, cumDelta[i] ?? null, bar.delta]

      for (let r = 0; r < values.length; r++) {
        const y = top + 4 + r * PARAM_ROW_H
        const h = PARAM_ROW_H - 3
        const v = values[r]
        if (v === null) {
          ctx.fillStyle = 'rgba(255,255,255,0.05)'
          ctx.fillRect(x, y, w, h)
          continue
        }
        ctx.fillStyle = paramColor(v)
        ctx.fillRect(x, y, w, h)
        if (showText) {
          ctx.fillStyle = paramInk(v)
          ctx.textAlign = 'center'
          const label = r === 0 ? `${v.toFixed(1)}%` : formatSize(v)
          ctx.fillText(label, x + w / 2, y + h / 2)
        }
      }
    }

    // row labels in the left margin
    ctx.fillStyle = 'rgba(13,17,24,0.92)'
    ctx.fillRect(0, top + 1, PARAM_LABEL_W, PARAM_PANE_H - 2)
    ctx.fillStyle = COLORS.text
    ctx.textAlign = 'right'
    for (let r = 0; r < PARAM_ROWS.length; r++) {
      ctx.fillText(PARAM_ROWS[r], PARAM_LABEL_W - 6, top + 4 + r * PARAM_ROW_H + (PARAM_ROW_H - 3) / 2)
    }
    ctx.strokeStyle = COLORS.separator
    ctx.beginPath()
    ctx.moveTo(0, Math.round(this.height - TIME_AXIS_H) + 0.5)
    ctx.lineTo(this.width, Math.round(this.height - TIME_AXIS_H) + 0.5)
    ctx.stroke()
  }

  private axisLabel(ctx: CanvasRenderingContext2D, y: number, text: string, bg: string, fg: string): void {
    ctx.font = '11px system-ui, sans-serif'
    ctx.fillStyle = bg
    ctx.fillRect(this.plotW, y - 9, AXIS_W, 18)
    ctx.fillStyle = fg
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(text, this.plotW + 6, y + 0.5)
  }

  private drawPriceAxis(ctx: CanvasRenderingContext2D, s: Scale): void {
    ctx.fillStyle = COLORS.axisBg
    ctx.fillRect(this.plotW, 0, AXIS_W, this.height)
    ctx.strokeStyle = COLORS.separator
    ctx.beginPath()
    ctx.moveTo(this.plotW + 0.5, 0)
    ctx.lineTo(this.plotW + 0.5, this.height)
    ctx.stroke()
    ctx.fillStyle = COLORS.text
    ctx.font = '11px system-ui, sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    for (const v of niceTicks(s.min, s.max, Math.max(2, Math.floor((s.bottom - s.top) / 50)))) {
      const y = this.yForPrice(v, s)
      if (y < 4 || y > s.bottom + 4) continue
      ctx.fillText(formatPrice(v), this.plotW + 6, y)
    }
    const last = this.series.bars[this.series.bars.length - 1]
    if (last) {
      const y = this.yForPrice(last.close, s)
      if (y >= s.top && y <= s.bottom) {
        const color = last.close >= last.open ? COLORS.up : COLORS.down
        ctx.save()
        ctx.strokeStyle = color
        ctx.setLineDash([3, 3])
        ctx.beginPath()
        ctx.moveTo(0, Math.round(y) + 0.5)
        ctx.lineTo(this.plotW, Math.round(y) + 0.5)
        ctx.stroke()
        ctx.restore()
        this.axisLabel(ctx, y, formatPrice(last.close), color, '#fff')
      }
    }
  }

  private drawTimeAxis(ctx: CanvasRenderingContext2D, ticks: { i: number; t: number }[]): void {
    const y0 = this.height - TIME_AXIS_H
    ctx.fillStyle = COLORS.axisBg
    ctx.fillRect(0, y0, this.width, TIME_AXIS_H)
    ctx.strokeStyle = COLORS.separator
    ctx.beginPath()
    ctx.moveTo(0, Math.round(y0) + 0.5)
    ctx.lineTo(this.width, Math.round(y0) + 0.5)
    ctx.stroke()
    ctx.fillStyle = COLORS.text
    ctx.font = '11px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    let prev: number | null = null
    for (const tick of ticks) {
      ctx.fillText(formatTimeTick(tick.t, prev, this.tfMs), this.xForIndex(tick.i), y0 + TIME_AXIS_H / 2)
      prev = tick.t
    }
  }

  // ------------------------------------------------------------- overlay

  private renderOverlay(): void {
    const ctx = this.overlay.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, this.width, this.height)
    const m = this.mouse
    const s = this.scale
    if (!m || !s || this.series.bars.length === 0 || m.x > this.plotW) return

    const idx = Math.round(this.indexForX(m.x))
    const bar = this.series.bars[idx]
    const x = this.xForIndex(idx)

    // column highlight
    if (bar) {
      ctx.fillStyle = 'rgba(255,255,255,0.05)'
      ctx.fillRect(x - this.colW / 2, 0, this.colW, this.height - TIME_AXIS_H)
    }

    ctx.strokeStyle = COLORS.crosshair
    ctx.setLineDash([4, 4])
    ctx.beginPath()
    ctx.moveTo(Math.round(x) + 0.5, 0)
    ctx.lineTo(Math.round(x) + 0.5, this.height - TIME_AXIS_H)
    if (m.y <= s.bottom + 4) {
      ctx.moveTo(0, Math.round(m.y) + 0.5)
      ctx.lineTo(this.plotW, Math.round(m.y) + 0.5)
    }
    ctx.stroke()
    ctx.setLineDash([])

    if (m.y <= s.bottom + 4) {
      this.axisLabel(ctx, m.y, formatPrice(this.priceForY(m.y, s)), '#363c4e', '#fff')
    }

    if (bar) {
      ctx.font = '11px system-ui, sans-serif'
      const label = formatFullTime(bar.time, this.tfMs)
      const w = ctx.measureText(label).width + 14
      ctx.fillStyle = '#363c4e'
      ctx.fillRect(Math.min(Math.max(0, x - w / 2), this.width - w), this.height - TIME_AXIS_H + 2, w, 20)
      ctx.fillStyle = '#fff'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, Math.min(Math.max(w / 2, x), this.width - w / 2), this.height - TIME_AXIS_H + 12)
    }
  }

  private hoveredLevel(): { bar: FootprintBar | null; level: HoveredLevel | null; index: number } {
    const m = this.mouse
    const s = this.scale
    if (!m || !s || m.x > this.plotW) return { bar: null, level: null, index: -1 }
    const index = Math.round(this.indexForX(m.x))
    const bar = this.series.bars[index] ?? null
    if (!bar || m.y > s.bottom) return { bar, level: null, index }
    const rowSize = this.series.rowSize
    const price = this.priceForY(m.y, s)
    const first = bar.levels[0]
    if (!first) return { bar, level: null, index }
    const r = Math.floor((price - first.price) / rowSize)
    const l = bar.levels[r]
    if (!l) return { bar, level: null, index }
    const imb = rowImbalances(bar.levels)[r] ?? 0
    return { bar, level: { price: l.price, bid: l.bid, ask: l.ask, imbalance: imb }, index }
  }

  private emitLegend(): void {
    if (!this.opts.onLegend) return
    const { bars, cumDelta, roc, rowSize, tradeCount } = this.series
    const hovered = this.hoveredLevel()
    const index = hovered.bar ? hovered.index : bars.length - 1
    this.opts.onLegend({
      bar: bars[index] ?? null,
      cumDelta: cumDelta[index] ?? null,
      roc: roc[index] ?? null,
      level: hovered.level,
      rowSize,
      bars: bars.length,
      trades: tradeCount,
    })
  }

  // ------------------------------------------------------------- interaction

  private onPointerDown = (e: PointerEvent): void => {
    const rect = this.overlay.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    this.overlay.setPointerCapture(e.pointerId)
    if (x > this.plotW) {
      // dragging the price axis stretches the price scale
      this.priceAnchor ??= this.scale ? (this.scale.min + this.scale.max) / 2 : null
      this.drag = { kind: 'scale', lastY: y }
      return
    }
    this.drag = { kind: 'pan', lastX: x, lastY: y }
    this.overlay.style.cursor = 'grabbing'
  }

  private onPointerMove = (e: PointerEvent): void => {
    const rect = this.overlay.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    this.mouse = { x, y }
    const s = this.scale

    if (this.drag?.kind === 'pan' && s) {
      const dx = x - this.drag.lastX
      const dy = y - this.drag.lastY
      this.drag.lastX = x
      this.drag.lastY = y
      this.rightIndex -= dx / this.colW
      const span = s.max - s.min
      const center = this.priceAnchor ?? (s.min + s.max) / 2
      this.priceAnchor = center + (dy * span) / Math.max(1, s.bottom - s.top)
      this.clampView()
      this.requestRender()
    } else if (this.drag?.kind === 'scale') {
      const dy = y - this.drag.lastY
      this.drag.lastY = y
      this.priceZoom = Math.max(0.2, Math.min(24, this.priceZoom * Math.exp(dy * 0.006)))
      this.requestRender()
    }
    this.emitLegend()
    this.requestOverlayRender()
  }

  private onPointerUp = (e: PointerEvent): void => {
    this.drag = null
    this.overlay.style.cursor = 'crosshair'
    try {
      this.overlay.releasePointerCapture(e.pointerId)
    } catch {
      /* not captured */
    }
  }

  private onPointerLeave = (): void => {
    this.mouse = null
    this.emitLegend()
    this.requestOverlayRender()
  }

  private onWheel = (e: WheelEvent): void => {
    e.preventDefault()
    const rect = this.overlay.getBoundingClientRect()
    const x = e.clientX - rect.left
    const anchorIdx = this.indexForX(x)
    this.colW = Math.max(MIN_COL_W, Math.min(MAX_COL_W, this.colW * Math.exp(-e.deltaY * 0.0015)))
    this.rightIndex = anchorIdx - (x - this.plotW) / this.colW
    this.clampView()
    this.requestRender()
  }

  private clampView(): void {
    const n = this.series.bars.length
    if (n === 0) return
    const visible = this.plotW / this.colW
    this.rightIndex = Math.max(1, Math.min(n - 1 + visible - 1, this.rightIndex))
  }
}

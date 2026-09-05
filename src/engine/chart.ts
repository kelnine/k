import type { Candle } from '../data/types'
import { indicatorById, type IndicatorDef, type IndicatorResult, type IndicatorShape } from '../indicators'
import {
  DEFAULT_COLOR,
  hitTestDrawing,
  POINTS_NEEDED,
  renderDrawing,
  type Drawing,
  type DrawingPoint,
  type DrawingTool,
  type DrawSpace,
} from './drawings'
import { formatFullTime, formatPrice, formatTimeTick, niceTicks } from './utils'

export interface LegendData {
  candle: Candle | null
  prev: Candle | null
  indicators: { name: string; items: { color: string; value: string }[] }[]
}

export interface EngineOptions {
  onLegend?(d: LegendData): void
  onToolFinished?(): void
  onDrawingsChange?(drawings: Drawing[]): void
  /** called once when the user pans near the oldest loaded candle */
  onLoadMore?(): void
}

interface ActiveInd {
  def: IndicatorDef
  result: IndicatorResult
}

interface PaneScale {
  top: number
  bottom: number
  min: number
  max: number
}

const COLORS = {
  bg: '#080b11',
  grid: 'rgba(255,255,255,0.04)',
  text: '#7d8699',
  textBright: '#e7eaf1',
  up: '#22c7a9',
  down: '#f6465d',
  axisBg: '#080b11',
  crosshair: 'rgba(180,190,210,0.55)',
  separator: 'rgba(255,255,255,0.09)',
  lastPriceUp: '#22c7a9',
  lastPriceDown: '#f6465d',
}

const AXIS_W = 72
const TIME_AXIS_H = 26
const DEFAULT_BAR_SPACING = 9
const RIGHT_OFFSET_BARS = 6

type DragState =
  | { kind: 'pan'; lastX: number }
  | { kind: 'handle'; drawing: Drawing; index: number }
  | { kind: 'move'; drawing: Drawing; startPoints: DrawingPoint[]; startX: number; startY: number }

export class ChartEngine {
  private container: HTMLElement
  private main: HTMLCanvasElement
  private overlay: HTMLCanvasElement
  private opts: EngineOptions
  private ro: ResizeObserver

  private candles: Candle[] = []
  private tfMs = 60_000
  private symbol = ''

  private barSpacing = DEFAULT_BAR_SPACING
  private rightIndex = 0 // fractional candle index aligned to the right edge of the plot area
  private width = 0
  private height = 0

  private indicators: ActiveInd[] = []
  private indicatorIds: string[] = []

  private drawings: Drawing[] = []
  private selectedId: string | null = null
  private tool: DrawingTool = 'cursor'
  private pending: { type: Exclude<DrawingTool, 'cursor'>; points: DrawingPoint[] } | null = null

  private mouse: { x: number; y: number } | null = null
  private drag: DragState | null = null
  private rafId = 0
  private overlayRafId = 0
  private loadMoreArmed = true
  private mainScale: PaneScale | null = null
  private paneScales: { ind: ActiveInd; scale: PaneScale }[] = []
  private destroyed = false

  constructor(container: HTMLElement, opts: EngineOptions = {}) {
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
    window.addEventListener('keydown', this.onKeyDown)
  }

  destroy(): void {
    this.destroyed = true
    this.ro.disconnect()
    window.removeEventListener('keydown', this.onKeyDown)
    cancelAnimationFrame(this.rafId)
    cancelAnimationFrame(this.overlayRafId)
    this.main.remove()
    this.overlay.remove()
  }

  // ------------------------------------------------------------- data

  setData(candles: Candle[], tfMs: number, symbol: string): void {
    this.candles = candles
    this.tfMs = tfMs
    this.symbol = symbol
    this.rightIndex = candles.length - 1 + RIGHT_OFFSET_BARS
    this.loadMoreArmed = true
    this.recomputeIndicators()
    this.requestRender()
    this.emitLegend()
  }

  prependData(older: Candle[]): void {
    if (older.length === 0) {
      this.loadMoreArmed = false // no more history available
      return
    }
    const firstTime = this.candles[0]?.time ?? Infinity
    const fresh = older.filter((c) => c.time < firstTime)
    this.candles = fresh.concat(this.candles)
    this.rightIndex += fresh.length
    this.loadMoreArmed = true
    this.recomputeIndicators()
    this.requestRender()
  }

  applyUpdate(c: Candle): void {
    const n = this.candles.length
    if (n === 0) return
    const last = this.candles[n - 1]
    if (c.time === last.time) {
      this.candles[n - 1] = c
    } else if (c.time > last.time) {
      const atRightEdge = this.rightIndex >= n - 2
      this.candles.push(c)
      if (atRightEdge) this.rightIndex += 1
    } else {
      return
    }
    this.recomputeIndicators()
    this.requestRender()
    if (!this.mouse) this.emitLegend()
  }

  setIndicators(ids: string[]): void {
    this.indicatorIds = ids
    this.recomputeIndicators()
    this.requestRender()
    this.emitLegend()
  }

  setDrawings(drawings: Drawing[]): void {
    this.drawings = drawings
    this.selectedId = null
    this.requestRender()
  }

  setTool(tool: DrawingTool): void {
    this.tool = tool
    this.pending = null
    if (tool !== 'cursor') this.selectedId = null
    this.requestOverlayRender()
  }

  deleteSelected(): void {
    if (!this.selectedId) return
    this.drawings = this.drawings.filter((d) => d.id !== this.selectedId)
    this.selectedId = null
    this.opts.onDrawingsChange?.(this.drawings)
    this.requestRender()
  }

  clearDrawings(): void {
    this.drawings = []
    this.selectedId = null
    this.opts.onDrawingsChange?.(this.drawings)
    this.requestRender()
  }

  resetView = (): void => {
    this.barSpacing = DEFAULT_BAR_SPACING
    this.rightIndex = this.candles.length - 1 + RIGHT_OFFSET_BARS
    this.requestRender()
  }

  private recomputeIndicators(): void {
    this.indicators = this.indicatorIds
      .map((id) => indicatorById(id))
      .filter((d): d is IndicatorDef => !!d)
      .map((def) => ({ def, result: def.compute(this.candles) }))
  }

  // ------------------------------------------------------------- geometry

  private get plotW(): number {
    return Math.max(0, this.width - AXIS_W)
  }

  private xForIndex(i: number): number {
    return this.plotW + (i - this.rightIndex) * this.barSpacing
  }

  private indexForX(x: number): number {
    return this.rightIndex + (x - this.plotW) / this.barSpacing
  }

  private timeToIndex(t: number): number {
    const c = this.candles
    const n = c.length
    if (n === 0) return 0
    if (t <= c[0].time) return (t - c[0].time) / this.tfMs
    if (t >= c[n - 1].time) return n - 1 + (t - c[n - 1].time) / this.tfMs
    let lo = 0
    let hi = n - 1
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1
      if (c[mid].time <= t) lo = mid
      else hi = mid
    }
    return lo + (t - c[lo].time) / (c[hi].time - c[lo].time)
  }

  private indexToTime(i: number): number {
    const c = this.candles
    const n = c.length
    if (n === 0) return 0
    if (i <= 0) return c[0].time + i * this.tfMs
    if (i >= n - 1) return c[n - 1].time + (i - (n - 1)) * this.tfMs
    const lo = Math.floor(i)
    return c[lo].time + (i - lo) * (c[lo + 1].time - c[lo].time)
  }

  private visibleRange(): [number, number] {
    const from = Math.max(0, Math.ceil(this.indexForX(0)))
    const to = Math.min(this.candles.length - 1, Math.floor(this.rightIndex))
    return [from, to]
  }

  /** pane layout: oscillator panes stacked under the main pane */
  private layoutPanes(): { mainTop: number; mainBottom: number; panes: { ind: ActiveInd; top: number; bottom: number }[] } {
    const paneInds = this.indicators.filter((a) => a.def.kind === 'pane')
    const drawable = Math.max(0, this.height - TIME_AXIS_H)
    const each = paneInds.length ? Math.min(0.2, 0.5 / paneInds.length) * drawable : 0
    const mainBottom = drawable - each * paneInds.length
    const panes = paneInds.map((ind, i) => ({
      ind,
      top: mainBottom + i * each,
      bottom: mainBottom + (i + 1) * each,
    }))
    return { mainTop: 0, mainBottom, panes }
  }

  private yForPrice(p: number, s: PaneScale): number {
    const span = s.max - s.min || 1
    return s.top + ((s.max - p) / span) * (s.bottom - s.top)
  }

  private priceForY(y: number, s: PaneScale): number {
    const span = s.max - s.min || 1
    return s.max - ((y - s.top) / (s.bottom - s.top)) * span
  }

  private drawSpace(): DrawSpace | null {
    const s = this.mainScale
    if (!s) return null
    return {
      xForTime: (t) => this.xForIndex(this.timeToIndex(t)),
      yForPrice: (p) => this.yForPrice(p, s),
      left: 0,
      right: this.plotW,
      top: s.top,
      bottom: s.bottom,
    }
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
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = COLORS.bg
    ctx.fillRect(0, 0, this.width, this.height)

    const { mainBottom, panes } = this.layoutPanes()
    const [from, to] = this.visibleRange()
    const hasData = this.candles.length > 0 && from <= to

    // ---- main pane price scale (candles + overlay indicator plots)
    let min = Infinity
    let max = -Infinity
    if (hasData) {
      for (let i = from; i <= to; i++) {
        min = Math.min(min, this.candles[i].low)
        max = Math.max(max, this.candles[i].high)
      }
      for (const a of this.indicators) {
        if (a.def.kind !== 'overlay') continue
        for (const plot of a.result.plots) {
          for (let i = from; i <= to; i++) {
            const v = plot.values[i]
            if (v !== null && v !== undefined) {
              min = Math.min(min, v)
              max = Math.max(max, v)
            }
          }
        }
      }
      const pad = (max - min || max * 0.01 || 1) * 0.08
      min -= pad
      max += pad
    } else {
      min = 0
      max = 1
    }
    this.mainScale = { top: 8, bottom: mainBottom - 4, min, max }

    const timeTicks = this.computeTimeTicks(from, to)
    this.drawGrid(ctx, this.mainScale, timeTicks, mainBottom)
    if (hasData) {
      this.drawWatermark(ctx, mainBottom)
      this.drawVolume(ctx, from, to, mainBottom)
      this.drawCandles(ctx, from, to, this.mainScale)
      this.drawOverlayIndicators(ctx, from, to, this.mainScale)
      this.drawIndicatorShapes(ctx, this.mainScale)
      this.drawLastPrice(ctx, this.mainScale)
      const sp = this.drawSpace()
      if (sp) for (const d of this.drawings) renderDrawing(ctx, sp, d, d.id === this.selectedId)
    }
    this.drawPriceAxis(ctx, this.mainScale)

    // ---- oscillator panes
    this.paneScales = []
    for (const p of panes) {
      const scale = this.computePaneScale(p.ind, from, to, p.top, p.bottom)
      this.paneScales.push({ ind: p.ind, scale })
      this.drawIndicatorPane(ctx, p.ind, from, to, scale, timeTicks)
    }

    this.drawTimeAxis(ctx, timeTicks)
  }

  private computeTimeTicks(from: number, to: number): { i: number; t: number }[] {
    if (this.candles.length === 0 || from > to) return []
    const stepBars = Math.max(1, Math.ceil(100 / this.barSpacing))
    const ticks: { i: number; t: number }[] = []
    const start = Math.ceil(from / stepBars) * stepBars
    for (let i = start; i <= to; i += stepBars) ticks.push({ i, t: this.candles[i].time })
    return ticks
  }

  private drawGrid(ctx: CanvasRenderingContext2D, s: PaneScale, timeTicks: { i: number }[], mainBottom: number): void {
    ctx.strokeStyle = COLORS.grid
    ctx.lineWidth = 1
    ctx.beginPath()
    for (const tick of timeTicks) {
      const x = Math.round(this.xForIndex(tick.i)) + 0.5
      ctx.moveTo(x, 0)
      ctx.lineTo(x, this.height - TIME_AXIS_H)
    }
    for (const v of niceTicks(s.min, s.max, Math.max(2, Math.floor((s.bottom - s.top) / 50)))) {
      const y = Math.round(this.yForPrice(v, s)) + 0.5
      ctx.moveTo(0, y)
      ctx.lineTo(this.plotW, y)
    }
    ctx.stroke()
    // separator between main pane and oscillators / time axis
    ctx.strokeStyle = COLORS.separator
    ctx.beginPath()
    ctx.moveTo(0, Math.round(mainBottom) + 0.5)
    ctx.lineTo(this.width, Math.round(mainBottom) + 0.5)
    ctx.stroke()
  }

  private drawWatermark(ctx: CanvasRenderingContext2D, mainBottom: number): void {
    ctx.save()
    ctx.fillStyle = 'rgba(255,255,255,0.04)'
    ctx.font = `700 ${Math.min(72, this.plotW / 8)}px system-ui, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(this.symbol, this.plotW / 2, mainBottom / 2)
    ctx.restore()
  }

  private drawVolume(ctx: CanvasRenderingContext2D, from: number, to: number, mainBottom: number): void {
    let maxVol = 0
    for (let i = from; i <= to; i++) maxVol = Math.max(maxVol, this.candles[i].volume)
    if (maxVol === 0) return
    const zone = (mainBottom - 8) * 0.18
    const bw = Math.max(1, this.barSpacing * 0.7)
    for (let i = from; i <= to; i++) {
      const c = this.candles[i]
      const h = (c.volume / maxVol) * zone
      const x = this.xForIndex(i)
      ctx.fillStyle = c.close >= c.open ? 'rgba(34,199,169,0.22)' : 'rgba(246,70,93,0.22)'
      ctx.fillRect(x - bw / 2, mainBottom - 4 - h, bw, h)
    }
  }

  private drawCandles(ctx: CanvasRenderingContext2D, from: number, to: number, s: PaneScale): void {
    const bw = Math.max(1, this.barSpacing * 0.7)
    const thin = this.barSpacing < 2.5
    for (let i = from; i <= to; i++) {
      const c = this.candles[i]
      const up = c.close >= c.open
      const color = up ? COLORS.up : COLORS.down
      const x = this.xForIndex(i)
      const yH = this.yForPrice(c.high, s)
      const yL = this.yForPrice(c.low, s)
      ctx.strokeStyle = color
      ctx.fillStyle = color
      if (thin) {
        ctx.fillRect(x - 0.5, yH, 1, Math.max(1, yL - yH))
        continue
      }
      const yO = this.yForPrice(c.open, s)
      const yC = this.yForPrice(c.close, s)
      ctx.beginPath()
      ctx.moveTo(x, yH)
      ctx.lineTo(x, yL)
      ctx.stroke()
      const top = Math.min(yO, yC)
      const h = Math.max(1, Math.abs(yC - yO))
      ctx.fillRect(x - bw / 2, top, bw, h)
    }
  }

  private strokePlot(
    ctx: CanvasRenderingContext2D,
    values: (number | null)[],
    from: number,
    to: number,
    yFor: (v: number) => number,
    color: string,
    width = 1.5,
  ): void {
    ctx.strokeStyle = color
    ctx.lineWidth = width
    ctx.beginPath()
    let started = false
    for (let i = from; i <= to; i++) {
      const v = values[i]
      if (v === null || v === undefined) {
        started = false
        continue
      }
      const x = this.xForIndex(i)
      const y = yFor(v)
      if (started) ctx.lineTo(x, y)
      else ctx.moveTo(x, y)
      started = true
    }
    ctx.stroke()
    ctx.lineWidth = 1
  }

  private drawOverlayIndicators(ctx: CanvasRenderingContext2D, from: number, to: number, s: PaneScale): void {
    for (const a of this.indicators) {
      if (a.def.kind !== 'overlay') continue
      for (const fill of a.result.fills ?? []) {
        const pa = a.result.plots.find((p) => p.key === fill.a)
        const pb = a.result.plots.find((p) => p.key === fill.b)
        if (!pa || !pb) continue
        ctx.fillStyle = fill.color
        ctx.beginPath()
        let started = false
        for (let i = from; i <= to; i++) {
          const v = pa.values[i]
          if (v === null || v === undefined) continue
          const x = this.xForIndex(i)
          if (started) ctx.lineTo(x, this.yForPrice(v, s))
          else ctx.moveTo(x, this.yForPrice(v, s))
          started = true
        }
        for (let i = to; i >= from; i--) {
          const v = pb.values[i]
          if (v === null || v === undefined) continue
          ctx.lineTo(this.xForIndex(i), this.yForPrice(v, s))
        }
        ctx.closePath()
        ctx.fill()
      }
      for (const plot of a.result.plots) {
        this.strokePlot(ctx, plot.values, from, to, (v) => this.yForPrice(v, s), plot.color, plot.width)
      }
    }
  }

  private drawIndicatorShapes(ctx: CanvasRenderingContext2D, s: PaneScale): void {
    const shapes: IndicatorShape[] = []
    for (const a of this.indicators) {
      if (a.def.kind === 'overlay' && a.result.shapes) shapes.push(...a.result.shapes)
    }
    if (shapes.length === 0) return

    ctx.save()
    ctx.beginPath()
    ctx.rect(0, 0, this.plotW, s.bottom + 4)
    ctx.clip()
    ctx.font = '10px system-ui, sans-serif'
    ctx.textBaseline = 'middle'

    for (const sh of shapes) {
      if (sh.type === 'box') {
        const ax = this.xForIndex(sh.x1)
        const bx = sh.x2 === null ? this.plotW : this.xForIndex(sh.x2)
        const left = Math.min(ax, bx)
        const right = Math.max(ax, bx)
        if (right < 0 || left > this.plotW) continue
        const yT = this.yForPrice(sh.yTop, s)
        const yB = this.yForPrice(sh.yBottom, s)
        const cl = Math.max(0, left)
        const cr = Math.min(this.plotW, right)
        ctx.fillStyle = sh.fill
        ctx.fillRect(cl, yT, cr - cl, yB - yT)
        if (sh.stroke) {
          ctx.strokeStyle = sh.stroke
          ctx.lineWidth = 1
          ctx.strokeRect(Math.round(cl) + 0.5, Math.round(yT) + 0.5, Math.round(cr - cl), Math.round(yB - yT))
        }
        if (sh.label && cr - cl > 26 && yB - yT > 12) {
          ctx.fillStyle = sh.labelColor ?? '#fff'
          ctx.textAlign = 'left'
          ctx.fillText(sh.label, cl + 3, (yT + yB) / 2)
        }
      } else if (sh.type === 'line') {
        const ax = this.xForIndex(sh.x1)
        const bx = sh.x2 === null ? this.plotW : this.xForIndex(sh.x2)
        if (Math.max(ax, bx) < 0 || Math.min(ax, bx) > this.plotW) continue
        const y1 = this.yForPrice(sh.y1, s)
        const y2 = this.yForPrice(sh.y2, s)
        ctx.strokeStyle = sh.color
        ctx.lineWidth = sh.width ?? 1
        if (sh.dash) ctx.setLineDash(sh.dash)
        ctx.beginPath()
        ctx.moveTo(ax, Math.round(y1) + 0.5)
        ctx.lineTo(bx, Math.round(y2) + 0.5)
        ctx.stroke()
        ctx.setLineDash([])
        ctx.lineWidth = 1
        if (sh.label) {
          const lx = Math.min(this.plotW - 2, Math.max(ax, bx))
          ctx.fillStyle = sh.labelColor ?? sh.color
          ctx.textAlign = 'right'
          ctx.fillText(sh.label, lx, y2 - 7)
        }
      } else {
        const x = this.xForIndex(sh.x)
        if (x < 0 || x > this.plotW) continue
        const y = this.yForPrice(sh.y, s)
        ctx.fillStyle = sh.color
        ctx.textAlign = 'center'
        ctx.textBaseline = sh.place === 'above' ? 'bottom' : 'top'
        ctx.fillText(sh.text, x, sh.place === 'above' ? y - 5 : y + 5)
        ctx.textBaseline = 'middle'
      }
    }
    ctx.restore()
  }

  private drawLastPrice(ctx: CanvasRenderingContext2D, s: PaneScale): void {
    const last = this.candles[this.candles.length - 1]
    if (!last) return
    const up = last.close >= last.open
    const color = up ? COLORS.lastPriceUp : COLORS.lastPriceDown
    const y = this.yForPrice(last.close, s)
    if (y < s.top || y > s.bottom) return
    ctx.strokeStyle = color
    ctx.setLineDash([3, 3])
    ctx.beginPath()
    ctx.moveTo(0, Math.round(y) + 0.5)
    ctx.lineTo(this.plotW, Math.round(y) + 0.5)
    ctx.stroke()
    ctx.setLineDash([])
    this.axisLabel(ctx, y, formatPrice(last.close), color, '#fff')
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

  private drawPriceAxis(ctx: CanvasRenderingContext2D, s: PaneScale): void {
    ctx.fillStyle = COLORS.axisBg
    ctx.fillRect(this.plotW, s.top - 8, AXIS_W, s.bottom - s.top + 12)
    ctx.strokeStyle = COLORS.separator
    ctx.beginPath()
    ctx.moveTo(this.plotW + 0.5, s.top - 8)
    ctx.lineTo(this.plotW + 0.5, this.height)
    ctx.stroke()
    ctx.fillStyle = COLORS.text
    ctx.font = '11px system-ui, sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    for (const v of niceTicks(s.min, s.max, Math.max(2, Math.floor((s.bottom - s.top) / 50)))) {
      ctx.fillText(formatPrice(v), this.plotW + 6, this.yForPrice(v, s))
    }
  }

  private computePaneScale(a: ActiveInd, from: number, to: number, top: number, bottom: number): PaneScale {
    if (a.result.range) {
      return { top: top + 6, bottom: bottom - 6, min: a.result.range[0], max: a.result.range[1] }
    }
    let min = Infinity
    let max = -Infinity
    for (const plot of a.result.plots) {
      for (let i = from; i <= to; i++) {
        const v = plot.values[i]
        if (v !== null && v !== undefined) {
          min = Math.min(min, v)
          max = Math.max(max, v)
        }
      }
    }
    if (!isFinite(min)) {
      min = 0
      max = 1
    }
    const pad = (max - min || 1) * 0.15
    return { top: top + 6, bottom: bottom - 6, min: min - pad, max: max + pad }
  }

  private drawIndicatorPane(
    ctx: CanvasRenderingContext2D,
    a: ActiveInd,
    from: number,
    to: number,
    s: PaneScale,
    timeTicks: { i: number }[],
  ): void {
    // grid + separator
    ctx.strokeStyle = COLORS.grid
    ctx.beginPath()
    for (const tick of timeTicks) {
      const x = Math.round(this.xForIndex(tick.i)) + 0.5
      ctx.moveTo(x, s.top - 6)
      ctx.lineTo(x, s.bottom + 6)
    }
    ctx.stroke()
    ctx.strokeStyle = COLORS.separator
    ctx.beginPath()
    ctx.moveTo(0, Math.round(s.bottom + 6) + 0.5)
    ctx.lineTo(this.width, Math.round(s.bottom + 6) + 0.5)
    ctx.stroke()

    for (const g of a.result.guides ?? []) {
      const y = this.yForPrice(g.value, s)
      ctx.strokeStyle = g.color
      ctx.setLineDash([4, 4])
      ctx.beginPath()
      ctx.moveTo(0, Math.round(y) + 0.5)
      ctx.lineTo(this.plotW, Math.round(y) + 0.5)
      ctx.stroke()
      ctx.setLineDash([])
    }

    for (const plot of a.result.plots) {
      if (plot.style === 'hist') {
        const zero = this.yForPrice(0, s)
        const bw = Math.max(1, this.barSpacing * 0.6)
        for (let i = from; i <= to; i++) {
          const v = plot.values[i]
          if (v === null || v === undefined) continue
          const prev = i > 0 ? plot.values[i - 1] : null
          const rising = prev !== null && prev !== undefined ? v >= prev : v >= 0
          ctx.fillStyle = v >= 0
            ? (rising ? 'rgba(34,199,169,0.9)' : 'rgba(34,199,169,0.45)')
            : (rising ? 'rgba(246,70,93,0.45)' : 'rgba(246,70,93,0.9)')
          const y = this.yForPrice(v, s)
          ctx.fillRect(this.xForIndex(i) - bw / 2, Math.min(y, zero), bw, Math.abs(zero - y) || 1)
        }
      } else {
        this.strokePlot(ctx, plot.values, from, to, (v) => this.yForPrice(v, s), plot.color, plot.width)
      }
    }

    // pane title + right-axis ticks
    ctx.fillStyle = COLORS.text
    ctx.font = '11px system-ui, sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'top'
    ctx.fillText(a.def.name, 8, s.top - 2)
    ctx.textBaseline = 'middle'
    for (const v of niceTicks(s.min, s.max, 3)) {
      ctx.fillText(formatPrice(v), this.plotW + 6, this.yForPrice(v, s))
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
    let prevT: number | null = null
    for (const tick of ticks) {
      ctx.fillText(formatTimeTick(tick.t, prevT, this.tfMs), this.xForIndex(tick.i), y0 + TIME_AXIS_H / 2)
      prevT = tick.t
    }
  }

  // ------------------------------------------------------------- overlay (crosshair, previews)

  private renderOverlay(): void {
    const ctx = this.overlay.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, this.width, this.height)
    const m = this.mouse
    const s = this.mainScale
    if (!m || !s || this.candles.length === 0) return

    const snapped = Math.round(this.indexForX(m.x))
    const x = this.xForIndex(snapped)

    if (m.x <= this.plotW && m.y <= this.height - TIME_AXIS_H) {
      ctx.strokeStyle = COLORS.crosshair
      ctx.setLineDash([4, 4])
      ctx.beginPath()
      ctx.moveTo(Math.round(x) + 0.5, 0)
      ctx.lineTo(Math.round(x) + 0.5, this.height - TIME_AXIS_H)
      ctx.moveTo(0, Math.round(m.y) + 0.5)
      ctx.lineTo(this.plotW, Math.round(m.y) + 0.5)
      ctx.stroke()
      ctx.setLineDash([])

      // y label in whichever pane the cursor is over
      const scaleAt = this.scaleAtY(m.y)
      if (scaleAt) this.axisLabel(ctx, m.y, formatPrice(this.priceForY(m.y, scaleAt)), '#363c4e', '#fff')

      // time label
      const t = this.indexToTime(snapped)
      ctx.font = '11px system-ui, sans-serif'
      const label = formatFullTime(t, this.tfMs)
      const w = ctx.measureText(label).width + 14
      ctx.fillStyle = '#363c4e'
      ctx.fillRect(Math.min(Math.max(0, x - w / 2), this.width - w), this.height - TIME_AXIS_H + 2, w, 20)
      ctx.fillStyle = '#fff'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, Math.min(Math.max(w / 2, x), this.width - w / 2), this.height - TIME_AXIS_H + 12)
    }

    // in-progress drawing preview
    const sp = this.drawSpace()
    if (this.pending && sp) {
      const preview: Drawing = {
        id: '__pending',
        type: this.pending.type,
        points: [...this.pending.points, this.pointAt(m.x, m.y)].slice(0, POINTS_NEEDED[this.pending.type]),
        color: DEFAULT_COLOR[this.pending.type],
        text: '…',
      }
      if (preview.points.length === POINTS_NEEDED[preview.type]) renderDrawing(ctx, sp, preview, false)
    }
  }

  private scaleAtY(y: number): PaneScale | null {
    const s = this.mainScale
    if (s && y <= s.bottom + 4) return s
    for (const p of this.paneScales) {
      if (y >= p.scale.top - 6 && y <= p.scale.bottom + 6) return p.scale
    }
    return null
  }

  private pointAt(x: number, y: number): DrawingPoint {
    const s = this.mainScale!
    return { time: this.indexToTime(this.indexForX(x)), price: this.priceForY(y, s) }
  }

  // ------------------------------------------------------------- legend

  private emitLegend(idx?: number): void {
    if (!this.opts.onLegend) return
    const n = this.candles.length
    if (n === 0) {
      this.opts.onLegend({ candle: null, prev: null, indicators: [] })
      return
    }
    const i = Math.max(0, Math.min(n - 1, idx ?? n - 1))
    const indicators = this.indicators.map((a) => ({
      name: a.def.name,
      items: a.result.legend ?? a.result.plots.map((p) => {
        const v = p.values[i]
        return { color: p.color, value: v === null || v === undefined ? '—' : formatPrice(v) }
      }),
    }))
    this.opts.onLegend({ candle: this.candles[i], prev: i > 0 ? this.candles[i - 1] : null, indicators })
  }

  // ------------------------------------------------------------- interaction

  private onPointerDown = (e: PointerEvent): void => {
    const rect = this.overlay.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    if (x > this.plotW) return
    this.overlay.setPointerCapture(e.pointerId)

    if (this.tool !== 'cursor' && this.mainScale) {
      this.handleToolClick(x, y)
      return
    }

    // drawings first, then pan
    const sp = this.drawSpace()
    if (sp) {
      for (let i = this.drawings.length - 1; i >= 0; i--) {
        const d = this.drawings[i]
        const hit = hitTestDrawing(sp, d, x, y)
        if (hit.hit) {
          this.selectedId = d.id
          this.drag =
            hit.handle !== undefined
              ? { kind: 'handle', drawing: d, index: hit.handle }
              : { kind: 'move', drawing: d, startPoints: d.points.map((p) => ({ ...p })), startX: x, startY: y }
          this.requestRender()
          return
        }
      }
    }
    if (this.selectedId) {
      this.selectedId = null
      this.requestRender()
    }
    this.drag = { kind: 'pan', lastX: x }
    this.overlay.style.cursor = 'grabbing'
  }

  private handleToolClick(x: number, y: number): void {
    const type = this.tool as Exclude<DrawingTool, 'cursor'>
    const pt = this.pointAt(x, y)
    if (!this.pending) this.pending = { type, points: [] }
    this.pending.points.push(pt)
    if (this.pending.points.length >= POINTS_NEEDED[type]) {
      const d: Drawing = {
        id: Math.random().toString(36).slice(2, 10),
        type,
        points: this.pending.points,
        color: DEFAULT_COLOR[type],
      }
      if (type === 'text') {
        const text = window.prompt('Note text:')
        if (!text) {
          this.pending = null
          this.opts.onToolFinished?.()
          this.requestOverlayRender()
          return
        }
        d.text = text
      }
      this.drawings.push(d)
      this.pending = null
      this.opts.onDrawingsChange?.(this.drawings)
      this.opts.onToolFinished?.()
      this.requestRender()
    } else {
      this.requestOverlayRender()
    }
  }

  private onPointerMove = (e: PointerEvent): void => {
    const rect = this.overlay.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    this.mouse = { x, y }

    if (this.drag) {
      switch (this.drag.kind) {
        case 'pan': {
          const dx = x - this.drag.lastX
          this.drag.lastX = x
          this.rightIndex -= dx / this.barSpacing
          this.clampView()
          this.maybeLoadMore()
          this.requestRender()
          break
        }
        case 'handle': {
          this.drag.drawing.points[this.drag.index] = this.pointAt(x, y)
          this.requestRender()
          break
        }
        case 'move': {
          const s = this.mainScale!
          const dIdx = (x - this.drag.startX) / this.barSpacing
          const dPrice = this.priceForY(y, s) - this.priceForY(this.drag.startY, s)
          this.drag.drawing.points = this.drag.startPoints.map((p) => ({
            time: this.indexToTime(this.timeToIndex(p.time) + dIdx),
            price: p.price + dPrice,
          }))
          this.requestRender()
          break
        }
      }
    } else {
      const snapped = Math.round(this.indexForX(x))
      this.emitLegend(snapped)
    }
    this.requestOverlayRender()
  }

  private onPointerUp = (e: PointerEvent): void => {
    if (this.drag && this.drag.kind !== 'pan') this.opts.onDrawingsChange?.(this.drawings)
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
    const factor = Math.exp(-e.deltaY * 0.0015)
    const newSpacing = Math.max(0.5, Math.min(60, this.barSpacing * factor))
    const anchorIdx = this.indexForX(x)
    this.barSpacing = newSpacing
    this.rightIndex = anchorIdx - (x - this.plotW) / this.barSpacing
    this.clampView()
    this.maybeLoadMore()
    this.requestRender()
  }

  private onKeyDown = (e: KeyboardEvent): void => {
    const target = e.target as HTMLElement
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return
    if ((e.key === 'Delete' || e.key === 'Backspace') && this.selectedId) {
      this.deleteSelected()
    } else if (e.key === 'Escape' && this.pending) {
      this.pending = null
      this.opts.onToolFinished?.()
      this.requestOverlayRender()
    }
  }

  private clampView(): void {
    const n = this.candles.length
    if (n === 0) return
    const visBars = this.plotW / this.barSpacing
    // keep at least 3 bars on screen at either extreme
    this.rightIndex = Math.max(3, Math.min(n - 1 + visBars - 3, this.rightIndex))
  }

  private maybeLoadMore(): void {
    if (!this.loadMoreArmed || !this.opts.onLoadMore) return
    if (this.indexForX(0) < 30) {
      this.loadMoreArmed = false
      this.opts.onLoadMore()
    }
  }
}

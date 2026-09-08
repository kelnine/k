import { formatPrice } from './utils'

export type DrawingTool =
  | 'cursor'
  | 'trendline'
  | 'hline'
  | 'fib'
  | 'text'
  | 'zone'
  | 'long'
  | 'short'
  | 'measure'
export type DrawingType = Exclude<DrawingTool, 'cursor'>

export interface DrawingPoint {
  time: number
  price: number
}

export interface Drawing {
  id: string
  type: DrawingType
  points: DrawingPoint[]
  text?: string
  color: string
}

export const POINTS_NEEDED: Record<DrawingType, number> = {
  trendline: 2,
  hline: 1,
  fib: 2,
  text: 1,
  zone: 2,
  // entry, target, stop
  long: 3,
  short: 3,
  measure: 2,
}

export const DEFAULT_COLOR: Record<DrawingType, string> = {
  trendline: '#2962ff',
  hline: '#ff9800',
  fib: '#787b86',
  text: '#e0e3eb',
  zone: '#d4c000',
  long: '#26a69a',
  short: '#ef5350',
  measure: '#22c55e',
}

const PROFIT_FILL = 'rgba(38,166,154,0.22)'
const PROFIT_EDGE = 'rgba(38,166,154,0.8)'
const RISK_FILL = 'rgba(239,83,80,0.22)'
const RISK_EDGE = 'rgba(239,83,80,0.8)'

/** `#rrggbb` + alpha → `rgba(...)`, for zone fills tinted from the tool colour. */
function tint(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.replace(/./g, (c) => c + c) : h, 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`
}

function pct(from: number, to: number): string {
  if (!from) return '—'
  const v = ((to - from) / from) * 100
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

/**
 * Price levels a drawing publishes to the right-hand price axis, so entries,
 * targets, stops and manual levels get a tag the way they do on TradingView.
 */
export function axisTags(d: Drawing): { price: number; color: string }[] {
  switch (d.type) {
    case 'hline':
      return [{ price: d.points[0].price, color: d.color }]
    case 'long':
    case 'short':
      if (d.points.length < 3) return []
      return [
        { price: d.points[0].price, color: '#4a5163' },
        { price: d.points[1].price, color: '#1f9d86' },
        { price: d.points[2].price, color: '#d84a47' },
      ]
    default:
      return []
  }
}

/** Pixel-space conversion context for the pane drawings live in. */
export interface DrawSpace {
  xForTime(t: number): number
  yForPrice(p: number): number
  left: number
  right: number
  top: number
  bottom: number
}

const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]
const FIB_COLORS = ['#787b86', '#ef5350', '#ff9800', '#fdd835', '#26a69a', '#26c6da', '#787b86']

function distToSegment(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const len2 = dx * dx + dy * dy
  let t = len2 === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / len2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

export interface HitResult {
  hit: boolean
  /** index of a grabbed endpoint, if the hit is on a handle */
  handle?: number
}

export function hitTestDrawing(sp: DrawSpace, d: Drawing, x: number, y: number): HitResult {
  const pts = d.points.map((p) => ({ x: sp.xForTime(p.time), y: sp.yForPrice(p.price) }))
  const HANDLE = 8
  for (let i = 0; i < pts.length; i++) {
    if (Math.abs(x - pts[i].x) <= HANDLE && Math.abs(y - pts[i].y) <= HANDLE) return { hit: true, handle: i }
  }
  const TOL = 6
  switch (d.type) {
    case 'trendline':
      if (pts.length === 2 && distToSegment(x, y, pts[0].x, pts[0].y, pts[1].x, pts[1].y) <= TOL)
        return { hit: true }
      break
    case 'hline':
      if (Math.abs(y - pts[0].y) <= TOL) return { hit: true }
      break
    case 'fib': {
      if (pts.length === 2) {
        const x1 = Math.min(pts[0].x, pts[1].x)
        const x2 = Math.max(pts[0].x, pts[1].x)
        for (const lvl of FIB_LEVELS) {
          const price = d.points[0].price + (d.points[1].price - d.points[0].price) * lvl
          const ly = sp.yForPrice(price)
          if (x >= x1 - TOL && x <= x2 + TOL && Math.abs(y - ly) <= TOL) return { hit: true }
        }
      }
      break
    }
    case 'text':
      if (Math.abs(x - pts[0].x) <= 50 && Math.abs(y - pts[0].y) <= 14) return { hit: true }
      break
    case 'zone': {
      // a zone spans the full pane width, so only its edges are grabbable —
      // clicking through the middle of the band still pans the chart
      if (pts.length !== 2) break
      if (Math.abs(y - pts[0].y) <= TOL || Math.abs(y - pts[1].y) <= TOL) return { hit: true }
      break
    }
    case 'long':
    case 'short': {
      if (pts.length !== 3) break
      const x1 = Math.min(pts[0].x, pts[1].x)
      const x2 = Math.max(pts[0].x, pts[1].x)
      const ys = pts.map((p) => p.y)
      if (x >= x1 - TOL && x <= x2 + TOL && y >= Math.min(...ys) - TOL && y <= Math.max(...ys) + TOL)
        return { hit: true }
      break
    }
    case 'measure': {
      if (pts.length !== 2) break
      const ax = Math.min(sp.right - 8, Math.max(sp.left + 8, Math.max(pts[0].x, pts[1].x)))
      if (distToSegment(x, y, ax, pts[0].y, ax, pts[1].y) <= TOL) return { hit: true }
      if (Math.abs(y - pts[0].y) <= TOL || Math.abs(y - pts[1].y) <= TOL) return { hit: true }
      break
    }
  }
  return { hit: false }
}

export function renderDrawing(
  ctx: CanvasRenderingContext2D,
  sp: DrawSpace,
  d: Drawing,
  selected: boolean,
): void {
  const pts = d.points.map((p) => ({ x: sp.xForTime(p.time), y: sp.yForPrice(p.price) }))
  ctx.save()
  ctx.beginPath()
  ctx.rect(sp.left, sp.top, sp.right - sp.left, sp.bottom - sp.top)
  ctx.clip()
  ctx.lineWidth = selected ? 2 : 1.5

  switch (d.type) {
    case 'trendline':
      if (pts.length === 2) {
        ctx.strokeStyle = d.color
        ctx.beginPath()
        ctx.moveTo(pts[0].x, pts[0].y)
        ctx.lineTo(pts[1].x, pts[1].y)
        ctx.stroke()
      }
      break

    case 'hline': {
      const y = pts[0].y
      ctx.strokeStyle = d.color
      ctx.setLineDash([6, 4])
      ctx.beginPath()
      ctx.moveTo(sp.left, y)
      ctx.lineTo(sp.right, y)
      ctx.stroke()
      ctx.setLineDash([])
      ctx.fillStyle = d.color
      ctx.font = '10px system-ui, sans-serif'
      ctx.textAlign = 'left'
      ctx.textBaseline = 'bottom'
      ctx.fillText(formatPrice(d.points[0].price), sp.left + 6, y - 3)
      break
    }

    case 'fib': {
      if (pts.length !== 2) break
      const x1 = Math.min(pts[0].x, pts[1].x)
      const x2 = Math.max(pts[0].x, pts[1].x)
      const p0 = d.points[0].price
      const p1 = d.points[1].price
      ctx.font = '10px system-ui, sans-serif'
      ctx.textAlign = 'right'
      ctx.textBaseline = 'bottom'
      for (let i = 0; i < FIB_LEVELS.length; i++) {
        const lvl = FIB_LEVELS[i]
        const price = p0 + (p1 - p0) * lvl
        const y = sp.yForPrice(price)
        ctx.strokeStyle = FIB_COLORS[i]
        ctx.beginPath()
        ctx.moveTo(x1, y)
        ctx.lineTo(x2, y)
        ctx.stroke()
        if (i > 0) {
          const prevY = sp.yForPrice(p0 + (p1 - p0) * FIB_LEVELS[i - 1])
          ctx.fillStyle = FIB_COLORS[i] + '14' // ~8% alpha band fill
          ctx.fillRect(x1, Math.min(y, prevY), x2 - x1, Math.abs(y - prevY))
        }
        ctx.fillStyle = FIB_COLORS[i]
        ctx.fillText(`${lvl} — ${formatPrice(price)}`, x2 - 4, y - 2)
      }
      // diagonal guide between anchors
      ctx.strokeStyle = 'rgba(120,123,134,0.5)'
      ctx.setLineDash([4, 4])
      ctx.beginPath()
      ctx.moveTo(pts[0].x, pts[0].y)
      ctx.lineTo(pts[1].x, pts[1].y)
      ctx.stroke()
      ctx.setLineDash([])
      break
    }

    case 'text': {
      const label = d.text ?? ''
      ctx.font = '12px system-ui, sans-serif'
      const w = ctx.measureText(label).width
      ctx.fillStyle = 'rgba(30,34,45,0.9)'
      ctx.strokeStyle = selected ? '#2962ff' : 'rgba(255,255,255,0.2)'
      const bx = pts[0].x - w / 2 - 6
      const by = pts[0].y - 11
      ctx.beginPath()
      ctx.roundRect(bx, by, w + 12, 22, 4)
      ctx.fill()
      ctx.stroke()
      ctx.fillStyle = d.color
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, pts[0].x, pts[0].y)
      break
    }

    case 'zone': {
      if (pts.length !== 2) break
      const yTop = Math.min(pts[0].y, pts[1].y)
      const yBot = Math.max(pts[0].y, pts[1].y)
      ctx.fillStyle = tint(d.color, 0.13)
      ctx.fillRect(sp.left, yTop, sp.right - sp.left, yBot - yTop)
      ctx.strokeStyle = tint(d.color, selected ? 0.9 : 0.5)
      ctx.beginPath()
      ctx.moveTo(sp.left, Math.round(yTop) + 0.5)
      ctx.lineTo(sp.right, Math.round(yTop) + 0.5)
      ctx.moveTo(sp.left, Math.round(yBot) + 0.5)
      ctx.lineTo(sp.right, Math.round(yBot) + 0.5)
      ctx.stroke()
      const hi = Math.max(d.points[0].price, d.points[1].price)
      const lo = Math.min(d.points[0].price, d.points[1].price)
      ctx.fillStyle = tint(d.color, 0.9)
      ctx.font = '10px system-ui, sans-serif'
      ctx.textAlign = 'right'
      ctx.textBaseline = 'top'
      ctx.fillText(`${formatPrice(lo)} – ${formatPrice(hi)}`, sp.right - 6, yTop + 3)
      break
    }

    case 'long':
    case 'short': {
      if (pts.length !== 3) break
      const entry = d.points[0].price
      const target = d.points[1].price
      const stop = d.points[2].price
      const x1 = Math.min(pts[0].x, pts[1].x)
      const x2 = Math.max(x1 + 30, Math.max(pts[0].x, pts[1].x))
      const yE = pts[0].y
      const yT = pts[1].y
      const yS = pts[2].y

      ctx.fillStyle = PROFIT_FILL
      ctx.fillRect(x1, Math.min(yE, yT), x2 - x1, Math.abs(yT - yE))
      ctx.fillStyle = RISK_FILL
      ctx.fillRect(x1, Math.min(yE, yS), x2 - x1, Math.abs(yS - yE))
      ctx.strokeStyle = PROFIT_EDGE
      ctx.strokeRect(x1, Math.min(yE, yT), x2 - x1, Math.abs(yT - yE))
      ctx.strokeStyle = RISK_EDGE
      ctx.strokeRect(x1, Math.min(yE, yS), x2 - x1, Math.abs(yS - yE))

      ctx.strokeStyle = '#e0e3eb'
      ctx.setLineDash([5, 3])
      ctx.beginPath()
      ctx.moveTo(x1, Math.round(yE) + 0.5)
      ctx.lineTo(x2, Math.round(yE) + 0.5)
      ctx.stroke()
      ctx.setLineDash([])

      const risk = Math.abs(entry - stop)
      const rr = risk > 0 ? Math.abs(target - entry) / risk : 0
      // a box may run past either edge (targets sit in the future), so keep the
      // labels pinned inside the pane rather than letting the clip eat them
      const lx = Math.max(sp.left + 5, x1 + 5)
      const rx = Math.min(sp.right - 5, x2 - 5)
      ctx.font = '10px system-ui, sans-serif'
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = '#7fe3d4'
      ctx.fillText(`TP ${formatPrice(target)} · ${pct(entry, target)}`, lx, (yE + yT) / 2)
      ctx.fillStyle = '#ffa6a4'
      ctx.fillText(`SL ${formatPrice(stop)} · ${pct(entry, stop)}`, lx, (yE + yS) / 2)
      ctx.fillStyle = '#e0e3eb'
      ctx.textAlign = 'right'
      ctx.fillText(
        `${d.type === 'long' ? 'LONG' : 'SHORT'} ${formatPrice(entry)} · R:R ${rr.toFixed(2)}`,
        rx,
        yE - 8,
      )
      break
    }

    case 'measure': {
      if (pts.length !== 2) break
      const from = d.points[0].price
      const to = d.points[1].price
      const up = to >= from
      const color = up ? '#22c55e' : '#ef5350'
      const ax = Math.min(sp.right - 8, Math.max(sp.left + 8, Math.max(pts[0].x, pts[1].x)))

      ctx.strokeStyle = tint(color, 0.85)
      ctx.beginPath()
      ctx.moveTo(sp.left, Math.round(pts[0].y) + 0.5)
      ctx.lineTo(sp.right, Math.round(pts[0].y) + 0.5)
      ctx.moveTo(sp.left, Math.round(pts[1].y) + 0.5)
      ctx.lineTo(sp.right, Math.round(pts[1].y) + 0.5)
      ctx.moveTo(ax, pts[0].y)
      ctx.lineTo(ax, pts[1].y)
      ctx.stroke()

      // arrowhead at the measured end
      const dir = pts[1].y < pts[0].y ? -1 : 1
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.moveTo(ax, pts[1].y)
      ctx.lineTo(ax - 5, pts[1].y - dir * 9)
      ctx.lineTo(ax + 5, pts[1].y - dir * 9)
      ctx.closePath()
      ctx.fill()

      const label = `${pct(from, to)}  (${formatPrice(Math.abs(to - from))})`
      ctx.font = '11px system-ui, sans-serif'
      const w = ctx.measureText(label).width + 12
      const bx = Math.min(sp.right - w - 2, Math.max(sp.left + 2, ax - w / 2))
      const by = pts[1].y + (dir < 0 ? -28 : 10)
      ctx.fillStyle = 'rgba(20,24,32,0.92)'
      ctx.strokeStyle = color
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.roundRect(bx, by, w, 19, 4)
      ctx.fill()
      ctx.stroke()
      ctx.fillStyle = color
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, bx + w / 2, by + 10)
      break
    }
  }

  if (selected) {
    for (const p of pts) {
      ctx.fillStyle = '#fff'
      ctx.strokeStyle = '#2962ff'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.arc(p.x, p.y, 4.5, 0, Math.PI * 2)
      ctx.fill()
      ctx.stroke()
    }
  }
  ctx.restore()
}

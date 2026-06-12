import { formatPrice } from './utils'

export type DrawingTool = 'cursor' | 'trendline' | 'hline' | 'fib' | 'text'
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
}

export const DEFAULT_COLOR: Record<DrawingType, string> = {
  trendline: '#2962ff',
  hline: '#ff9800',
  fib: '#787b86',
  text: '#e0e3eb',
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

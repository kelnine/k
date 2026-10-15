// The account's mark-to-market equity curve (equity_snapshots), with the balance and
// the starting balance for reference. Plain SVG: a few hundred points, no library.

import { useMemo, useRef, useState, type PointerEvent } from 'react'
import type { Equity } from '../api/types'
import { dateTime, money, toNumber } from '../lib/format'
import { Empty } from './ui'

const W = 800
const H = 220
const PAD = { left: 8, right: 64, top: 10, bottom: 22 }

export function EquityCurve({ data }: { data: Equity }) {
  const ref = useRef<SVGSVGElement>(null)
  const [hover, setHover] = useState<number | null>(null)
  const start = toNumber(data.starting_balance) ?? 0

  const geometry = useMemo(() => {
    const points = data.points.map((p) => ({
      t: Date.parse(p.ts),
      equity: Number(p.equity),
      balance: Number(p.balance),
    }))
    if (!points.length) return null
    const t0 = points[0].t
    const t1 = points[points.length - 1].t
    let lo = start
    let hi = start
    for (const p of points) {
      lo = Math.min(lo, p.equity, p.balance)
      hi = Math.max(hi, p.equity, p.balance)
    }
    const span = hi - lo || Math.max(1, hi * 0.001)
    lo -= span * 0.08
    hi += span * 0.08
    const x = (t: number) => PAD.left + ((t - t0) / Math.max(1, t1 - t0)) * (W - PAD.left - PAD.right)
    const y = (v: number) => PAD.top + ((hi - v) / (hi - lo)) * (H - PAD.top - PAD.bottom)
    const path = (key: 'equity' | 'balance') =>
      points.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p[key]).toFixed(1)}`).join('')
    const ticks = [hi - (hi - lo) * 0.08, (hi + lo) / 2, lo + (hi - lo) * 0.08]
    return { points, x, y, equityPath: path('equity'), balancePath: path('balance'), ticks, t0, t1 }
  }, [data, start])

  if (!geometry) return <Empty title="No equity snapshots yet">The curve starts with the account's first marked batch.</Empty>
  const { points, x, y } = geometry
  const last = points[points.length - 1]
  const up = last.equity >= start

  const onMove = (event: PointerEvent<SVGSVGElement>) => {
    const box = ref.current?.getBoundingClientRect()
    if (!box) return
    const px = ((event.clientX - box.left) / box.width) * W
    let best = 0
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(x(points[i].t) - px) < Math.abs(x(points[best].t) - px)) best = i
    }
    setHover(best)
  }
  const h = hover !== null ? points[hover] : null

  return (
    <div className="equity">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" onPointerMove={onMove} onPointerLeave={() => setHover(null)} role="img" aria-label="Equity curve">
        <line x1={PAD.left} x2={W - PAD.right} y1={y(start)} y2={y(start)} className="eq-start" />
        <path d={geometry.balancePath} className="eq-balance" />
        <path d={`${geometry.equityPath}L${x(last.t).toFixed(1)},${H - PAD.bottom}L${PAD.left},${H - PAD.bottom}Z`} className={`eq-fill ${up ? 'up' : 'down'}`} />
        <path d={geometry.equityPath} className={`eq-line ${up ? 'up' : 'down'}`} />
        {geometry.ticks.map((v) => (
          <text key={v} x={W - PAD.right + 6} y={y(v) + 4} className="eq-tick">
            {money(v, { compact: true })}
          </text>
        ))}
        <text x={PAD.left} y={H - 6} className="eq-tick">
          {dateTime(new Date(geometry.t0).toISOString())}
        </text>
        <text x={W - PAD.right} y={H - 6} className="eq-tick" textAnchor="end">
          {dateTime(new Date(geometry.t1).toISOString())}
        </text>
        {h && (
          <>
            <line x1={x(h.t)} x2={x(h.t)} y1={PAD.top} y2={H - PAD.bottom} className="eq-cross" />
            <circle cx={x(h.t)} cy={y(h.equity)} r={3.5} className="eq-dot" />
          </>
        )}
      </svg>
      <div className="equity-legend">
        {h ? (
          <>
            {dateTime(new Date(h.t).toISOString())} · equity <strong>{money(h.equity)}</strong> · balance {money(h.balance)}
          </>
        ) : (
          <>
            <span className="key eq-key-equity" /> equity <span className="key eq-key-balance" /> balance <span className="key eq-key-start" /> start {money(start)}
            {data.downsampled && <span className="muted"> · {data.points.length} of {data.total_points} snapshots</span>}
          </>
        )}
      </div>
    </div>
  )
}

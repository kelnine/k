export function formatPrice(p: number): string {
  const abs = Math.abs(p)
  if (abs === 0) return '0.00'
  if (abs >= 1000) return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (abs >= 10) return p.toFixed(2)
  if (abs >= 1) return p.toFixed(3)
  if (abs >= 0.01) return p.toFixed(5)
  return p.toFixed(8)
}

export function formatCompact(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1e9) return (v / 1e9).toFixed(2) + 'B'
  if (abs >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  if (abs >= 1e3) return (v / 1e3).toFixed(2) + 'K'
  return v.toFixed(2)
}

/** "Nice" axis tick values covering [min, max]. */
export function niceTicks(min: number, max: number, maxTicks: number): number[] {
  if (!(max > min) || maxTicks < 1) return []
  const span = max - min
  const rough = span / maxTicks
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  let step = mag
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (mag * m >= rough) {
      step = mag * m
      break
    }
  }
  const ticks: number[] = []
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) ticks.push(v)
  return ticks
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function pad(n: number): string {
  return n < 10 ? '0' + n : String(n)
}

/** Label for a time-axis tick; shows date at day boundaries, time otherwise. */
export function formatTimeTick(t: number, prevT: number | null, tfMs: number): string {
  const d = new Date(t)
  if (tfMs >= 86_400_000) {
    const p = prevT !== null ? new Date(prevT) : null
    if (!p || p.getUTCFullYear() !== d.getUTCFullYear()) return String(d.getUTCFullYear())
    if (p.getUTCMonth() !== d.getUTCMonth()) return MONTHS[d.getUTCMonth()]
    return `${d.getUTCDate()}`
  }
  const p = prevT !== null ? new Date(prevT) : null
  if (!p || p.getUTCDate() !== d.getUTCDate() || p.getUTCMonth() !== d.getUTCMonth()) {
    return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`
  }
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}

export function formatFullTime(t: number, tfMs: number): string {
  const d = new Date(t)
  const date = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`
  if (tfMs >= 86_400_000) return date
  return `${date} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}

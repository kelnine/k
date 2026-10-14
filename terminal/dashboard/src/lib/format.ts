// Display formatting. Values arrive as decimal strings; they become numbers only here,
// for display. Times are shown in UTC, like every timestamp the terminal stores.

export type Numeric = string | number | null | undefined

const MINUS = '−' // U+2212: lines up with "+" in tabular figures

export function toNumber(value: Numeric): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

function group(n: number, digits: number): string {
  return Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function withSign(n: number, text: string, signed: boolean): string {
  if (n < 0) return `${MINUS}${text}`
  if (signed && n > 0) return `+${text}`
  return text
}

/** `$50,000.00`; signed: `+$1,234.56` / `−$12.00`; compact: `$1.2M`. Empty value: `—`. */
export function money(
  value: Numeric,
  { signed = false, currency = 'USD', compact = false }: { signed?: boolean; currency?: string; compact?: boolean } = {},
): string {
  const n = toNumber(value)
  if (n === null) return '—'
  const symbol = currency === 'USD' ? '$' : ''
  const suffix = currency === 'USD' ? '' : ` ${currency}`
  let body: string
  if (compact && Math.abs(n) >= 1e6) body = `${(Math.abs(n) / 1e6).toFixed(2)}M`
  else if (compact && Math.abs(n) >= 1e4) body = `${(Math.abs(n) / 1e3).toFixed(1)}K`
  else body = group(n, 2)
  return withSign(n, `${symbol}${body}${suffix}`, signed)
}

/** A value already in percent (e.g. return_pct `2.85`): `2.85%`, signed `+2.85%`. */
export function pct(value: Numeric, { signed = false, digits = 2 }: { signed?: boolean; digits?: number } = {}): string {
  const n = toNumber(value)
  if (n === null) return '—'
  return withSign(n, `${Math.abs(n).toFixed(digits)}%`, signed)
}

/** A ratio 0..1 (e.g. win_rate `0.6364`) as a percentage: `63.6%`. */
export function ratio(value: Numeric, digits = 1): string {
  const n = toNumber(value)
  return n === null ? '—' : `${(n * 100).toFixed(digits)}%`
}

/** An R multiple: `+0.58R`, `−1.00R`. */
export function rMultiple(value: Numeric, digits = 2): string {
  const n = toNumber(value)
  if (n === null) return '—'
  return withSign(n, `${Math.abs(n).toFixed(digits)}R`, true)
}

/** Plain number with fixed decimals: `1.55`. */
export function fixed(value: Numeric, digits = 2): string {
  const n = toNumber(value)
  return n === null ? '—' : withSign(n, Math.abs(n).toFixed(digits), false)
}

/** A price or quantity as stored (`4345.7800000000` → `4,345.78`): trailing zeros
 *  dropped, at least `minDigits` decimals kept, thousands grouped. */
export function decimal(value: Numeric, minDigits = 2): string {
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value)
  const n = toNumber(text)
  if (n === null) return '—'
  const fraction = text.includes('.') ? text.split('.')[1].replace(/0+$/, '') : ''
  const digits = Math.max(minDigits, Math.min(fraction.length, 10))
  return withSign(n, group(n, digits), false)
}

export function qty(value: Numeric): string {
  return decimal(value, 0)
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

/** `2026-01-14 04:00` (UTC). */
export function dateTime(iso: string | null | undefined, { seconds = false }: { seconds?: boolean } = {}): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const date = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
  const time = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}${seconds ? `:${pad(d.getUTCSeconds())}` : ''}`
  return `${date} ${time}`
}

/** `5s ago`, `3m ago`, `2h ago`, `4d ago` relative to `now` (ms). */
export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const s = Math.round((now - t) / 1000)
  if (s < 0) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/** Seconds as `42s`, `3m 05s`, `1h 25m`, `2d 3h`. */
export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const s = Math.max(0, Math.round(value))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${pad(s % 60)}s`
  if (s < 86400) return `${Math.floor(s / 3600)}h ${pad(Math.floor((s % 3600) / 60))}m`
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`
}

/** Time between two ISO instants (`1h 25m`), or until now when `to` is missing. */
export function between(from: string | null | undefined, to: string | null | undefined, now = Date.now()): string {
  if (!from) return '—'
  const start = new Date(from).getTime()
  const end = to ? new Date(to).getTime() : now
  return seconds((end - start) / 1000)
}

/** CSS class for a signed value: `up`, `down` or `''`. */
export function tone(value: Numeric): 'up' | 'down' | '' {
  const n = toNumber(value)
  if (n === null || n === 0) return ''
  return n > 0 ? 'up' : 'down'
}

export function shortId(id: string | null | undefined, length = 8): string {
  return id ? id.slice(0, length) : '—'
}

/** Strategy parameters as `fast=9 slow=21`. */
export function params(values: Record<string, unknown> | null | undefined): string {
  if (!values) return ''
  return Object.entries(values)
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join(' ')
}

/** `SESSION_CLOSE` → `Session close`. */
export function label(code: string | null | undefined): string {
  if (!code) return '—'
  const words = code.toLowerCase().split('_')
  return [words[0].charAt(0).toUpperCase() + words[0].slice(1), ...words.slice(1)].join(' ')
}

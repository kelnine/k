import type { Candle } from '../src/data/types'
import { TF_MS } from '../src/data/types'

const REST = 'https://api.binance.com/api/v3'

type Raw = [number, string, string, string, string, string, ...unknown[]]

// ── demo / offline mode ───────────────────────────────────────────────────────

const BASE_PRICE: Record<string, number> = {
  BTCUSDT: 67000, ETHUSDT: 3500, SOLUSDT: 160, BNBUSDT: 590,
  XRPUSDT: 0.52, DOGEUSDT: 0.14,
}

function hashStr(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) }
  return h >>> 0
}

function noise(seed: number, t: number, period: number): number {
  const cell = Math.floor(t / period)
  const frac = (t - cell * period) / period
  const rnd = (c: number) => {
    let x = Math.imul(c ^ seed, 0x9e3779b1) >>> 0
    x = Math.imul(x ^ (x >>> 15), 0x85ebca6b) >>> 0
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0
    return ((x >>> 0) / 0xffffffff) * 2 - 1
  }
  const u = frac * frac * (3 - 2 * frac)
  return rnd(cell) + (rnd(cell + 1) - rnd(cell)) * u
}

function demoPrice(symbol: string, t: number): number {
  const seed = hashStr(symbol)
  const base = BASE_PRICE[symbol] ?? 100
  const day = 86_400_000
  const v =
    noise(seed, t, 30 * day) * 0.45 +
    noise(seed ^ 0xabcd, t, 3 * day) * 0.18 +
    noise(seed ^ 0x1234, t, 4 * 3_600_000) * 0.06 +
    noise(seed ^ 0x77aa, t, 5 * 60_000) * 0.02
  return base * Math.exp(v)
}

function demoCandle(symbol: string, bucket: number, tfMs: number): Candle {
  const end = bucket + tfMs
  const steps = 8
  let high = -Infinity, low = Infinity
  const open = demoPrice(symbol, bucket)
  let close = open
  for (let i = 0; i <= steps; i++) {
    const p = demoPrice(symbol, bucket + ((end - bucket) * i) / steps)
    high = Math.max(high, p); low = Math.min(low, p); close = p
  }
  return { time: bucket, open, high, low, close, volume: 100 }
}

function demoFetchCandles(symbol: string, tf: string, limit: number): Candle[] {
  const tfMs = TF_MS[tf as keyof typeof TF_MS] ?? 3_600_000
  const now = Date.now()
  const lastBucket = Math.floor(now / tfMs) * tfMs
  const out: Candle[] = []
  for (let i = limit - 1; i >= 0; i--) out.push(demoCandle(symbol, lastBucket - i * tfMs, tfMs))
  return out
}

// ── Binance REST ─────────────────────────────────────────────────────────────

export async function fetchCandles(symbol: string, tf: string, limit: number): Promise<Candle[]> {
  if (process.env.BOT_DEMO === 'true') return demoFetchCandles(symbol, tf, limit)
  const res = await fetch(`${REST}/klines?symbol=${symbol}&interval=${tf}&limit=${limit}`)
  if (!res.ok) throw new Error(`Binance klines ${res.status} for ${symbol}`)
  const raw = (await res.json()) as Raw[]
  return raw.map((r) => ({
    time: r[0],
    open: parseFloat(r[1]),
    high: parseFloat(r[2]),
    low: parseFloat(r[3]),
    close: parseFloat(r[4]),
    volume: parseFloat(r[5]),
  }))
}

export async function fetchPrice(symbol: string): Promise<number> {
  if (process.env.BOT_DEMO === 'true') return demoPrice(symbol, Date.now())
  const res = await fetch(`${REST}/ticker/price?symbol=${symbol}`)
  if (!res.ok) throw new Error(`Binance price ${res.status} for ${symbol}`)
  const data = (await res.json()) as { price: string }
  return parseFloat(data.price)
}

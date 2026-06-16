import type { Candle, DataAdapter, SymbolInfo, Ticker, Timeframe } from './types'
import { TF_MS } from './types'

/**
 * Deterministic synthetic market data. price(symbol, t) is a pure function of
 * time, so any range of history can be generated on demand and always agrees
 * with itself — pan back as far as you like.
 */

const DEMO_SYMBOLS: SymbolInfo[] = [
  ['BTCUSDT', 'BTC', 67000],
  ['ETHUSDT', 'ETH', 3500],
  ['SOLUSDT', 'SOL', 160],
  ['BNBUSDT', 'BNB', 590],
  ['XRPUSDT', 'XRP', 0.52],
  ['DOGEUSDT', 'DOGE', 0.14],
  ['ADAUSDT', 'ADA', 0.45],
  ['AVAXUSDT', 'AVAX', 28],
  ['LINKUSDT', 'LINK', 14.5],
  ['DOTUSDT', 'DOT', 6.2],
].map(([symbol, base]) => ({
  symbol: symbol as string,
  base: base as string,
  quote: 'USDT',
  description: `${base} / USDT (demo)`,
}))

const BASE_PRICE: Record<string, number> = {
  BTCUSDT: 67000, ETHUSDT: 3500, SOLUSDT: 160, BNBUSDT: 590, XRPUSDT: 0.52,
  DOGEUSDT: 0.14, ADAUSDT: 0.45, AVAXUSDT: 28, LINKUSDT: 14.5, DOTUSDT: 6.2,
}

function hashStr(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** Stateless value noise in [-1, 1], smooth-ish over `period` ms. */
function noise(seed: number, t: number, period: number): number {
  const cell = Math.floor(t / period)
  const frac = (t - cell * period) / period
  const rnd = (c: number) => {
    let x = Math.imul(c ^ seed, 0x9e3779b1) >>> 0
    x = Math.imul(x ^ (x >>> 15), 0x85ebca6b) >>> 0
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0
    return ((x >>> 0) / 0xffffffff) * 2 - 1
  }
  const a = rnd(cell)
  const b = rnd(cell + 1)
  const u = frac * frac * (3 - 2 * frac) // smoothstep
  return a + (b - a) * u
}

function price(symbol: string, t: number): number {
  const seed = hashStr(symbol)
  const base = BASE_PRICE[symbol] ?? 100
  const day = 86_400_000
  // layered noise: macro trend, daily swing, hourly chop, minute jitter
  const v =
    noise(seed, t, 30 * day) * 0.45 +
    noise(seed ^ 0xabcd, t, 3 * day) * 0.18 +
    noise(seed ^ 0x1234, t, 4 * 3_600_000) * 0.06 +
    noise(seed ^ 0x77aa, t, 5 * 60_000) * 0.02
  return base * Math.exp(v)
}

function buildCandle(symbol: string, bucket: number, tfMs: number, until?: number): Candle {
  const end = until !== undefined ? Math.min(until, bucket + tfMs) : bucket + tfMs
  const steps = 8
  let high = -Infinity
  let low = Infinity
  const open = price(symbol, bucket)
  let close = open
  for (let i = 0; i <= steps; i++) {
    const t = bucket + ((end - bucket) * i) / steps
    const p = price(symbol, t)
    high = Math.max(high, p)
    low = Math.min(low, p)
    close = p
  }
  const seed = hashStr(symbol)
  const volume = (Math.abs(noise(seed ^ 0x5151, bucket, tfMs * 3)) + 0.15) * 1000 * (tfMs / 60_000)
  return { time: bucket, open, high, low, close, volume }
}

export class DemoAdapter implements DataAdapter {
  id = 'demo'
  name = 'Demo data'

  async searchSymbols(query: string): Promise<SymbolInfo[]> {
    const q = query.trim().toUpperCase()
    return DEMO_SYMBOLS.filter((s) => !q || s.symbol.includes(q) || s.base.includes(q))
  }

  async fetchCandles(symbol: string, tf: Timeframe, limit: number, endTime?: number): Promise<Candle[]> {
    const tfMs = TF_MS[tf]
    const now = Date.now()
    const lastBucket =
      endTime !== undefined
        ? Math.floor((endTime - 1) / tfMs) * tfMs
        : Math.floor(now / tfMs) * tfMs
    const out: Candle[] = []
    for (let i = limit - 1; i >= 0; i--) {
      const bucket = lastBucket - i * tfMs
      out.push(buildCandle(symbol, bucket, tfMs, endTime === undefined ? now : undefined))
    }
    return out
  }

  subscribeCandles(symbol: string, tf: Timeframe, onCandle: (c: Candle) => void): () => void {
    const tfMs = TF_MS[tf]
    const timer = setInterval(() => {
      const now = Date.now()
      const bucket = Math.floor(now / tfMs) * tfMs
      onCandle(buildCandle(symbol, bucket, tfMs, now))
    }, 1000)
    return () => clearInterval(timer)
  }

  subscribeTicker(symbol: string, onTick: (t: Ticker) => void): () => void {
    const tick = () => {
      const now = Date.now()
      const last = price(symbol, now)
      const open = price(symbol, now - 86_400_000)
      onTick({ symbol, last, changePct: ((last - open) / open) * 100 })
    }
    tick()
    const timer = setInterval(tick, 1500)
    return () => clearInterval(timer)
  }
}

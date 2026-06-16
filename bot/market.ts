import type { Candle } from '../src/data/types'

const REST = 'https://api.binance.com/api/v3'

type Raw = [number, string, string, string, string, string, ...unknown[]]

export async function fetchCandles(symbol: string, tf: string, limit: number): Promise<Candle[]> {
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
  const res = await fetch(`${REST}/ticker/price?symbol=${symbol}`)
  if (!res.ok) throw new Error(`Binance price ${res.status} for ${symbol}`)
  const data = (await res.json()) as { price: string }
  return parseFloat(data.price)
}

import type { Candle, DataAdapter, SymbolInfo, Ticker, Timeframe } from './types'

const REST = 'https://api.binance.com/api/v3'
const WS = 'wss://stream.binance.com:9443/ws'

// Binance interval strings happen to match our Timeframe ids exactly.
type Raw = [number, string, string, string, string, string, ...unknown[]]

function toCandle(r: Raw): Candle {
  return {
    time: r[0],
    open: parseFloat(r[1]),
    high: parseFloat(r[2]),
    low: parseFloat(r[3]),
    close: parseFloat(r[4]),
    volume: parseFloat(r[5]),
  }
}

/** WebSocket that re-dials with backoff until closed via the returned fn. */
function persistentSocket(url: string, onMessage: (data: any) => void): () => void {
  let ws: WebSocket | null = null
  let closed = false
  let retry = 1000

  const dial = () => {
    if (closed) return
    ws = new WebSocket(url)
    ws.onmessage = (ev) => {
      retry = 1000
      try {
        onMessage(JSON.parse(ev.data))
      } catch {
        /* ignore malformed frames */
      }
    }
    ws.onclose = () => {
      if (!closed) {
        setTimeout(dial, retry)
        retry = Math.min(retry * 2, 15_000)
      }
    }
    ws.onerror = () => ws?.close()
  }
  dial()

  return () => {
    closed = true
    ws?.close()
  }
}

export class BinanceAdapter implements DataAdapter {
  id = 'binance'
  name = 'Binance'
  private symbolsCache: Promise<SymbolInfo[]> | null = null

  static async available(timeoutMs = 3000): Promise<boolean> {
    try {
      const res = await fetch(`${REST}/ping`, { signal: AbortSignal.timeout(timeoutMs) })
      return res.ok
    } catch {
      return false
    }
  }

  private allSymbols(): Promise<SymbolInfo[]> {
    this.symbolsCache ??= fetch(`${REST}/exchangeInfo`)
      .then((r) => r.json())
      .then((j) =>
        (j.symbols as any[])
          .filter((s) => s.status === 'TRADING' && s.isSpotTradingAllowed)
          .map((s) => ({
            symbol: s.symbol as string,
            base: s.baseAsset as string,
            quote: s.quoteAsset as string,
            description: `${s.baseAsset} / ${s.quoteAsset}`,
          })),
      )
    return this.symbolsCache
  }

  async searchSymbols(query: string): Promise<SymbolInfo[]> {
    const all = await this.allSymbols()
    const q = query.trim().toUpperCase()
    if (!q) return all.filter((s) => s.quote === 'USDT').slice(0, 30)
    const scored = all
      .filter((s) => s.symbol.includes(q) || s.base.includes(q))
      .sort((a, b) => {
        // exact base + USDT quote first, then shorter symbols
        const rank = (s: SymbolInfo) =>
          (s.base === q ? 0 : s.symbol.startsWith(q) ? 1 : 2) + (s.quote === 'USDT' ? 0 : 0.5)
        return rank(a) - rank(b) || a.symbol.length - b.symbol.length
      })
    return scored.slice(0, 30)
  }

  async fetchCandles(symbol: string, tf: Timeframe, limit: number, endTime?: number): Promise<Candle[]> {
    const params = new URLSearchParams({ symbol, interval: tf, limit: String(limit) })
    if (endTime !== undefined) params.set('endTime', String(endTime - 1))
    const res = await fetch(`${REST}/klines?${params}`)
    if (!res.ok) throw new Error(`Binance klines ${res.status}`)
    const raw = (await res.json()) as Raw[]
    return raw.map(toCandle)
  }

  subscribeCandles(symbol: string, tf: Timeframe, onCandle: (c: Candle) => void): () => void {
    return persistentSocket(`${WS}/${symbol.toLowerCase()}@kline_${tf}`, (msg) => {
      const k = msg?.k
      if (!k) return
      onCandle({
        time: k.t,
        open: parseFloat(k.o),
        high: parseFloat(k.h),
        low: parseFloat(k.l),
        close: parseFloat(k.c),
        volume: parseFloat(k.v),
      })
    })
  }

  subscribeTicker(symbol: string, onTick: (t: Ticker) => void): () => void {
    return persistentSocket(`${WS}/${symbol.toLowerCase()}@miniTicker`, (msg) => {
      if (!msg?.c) return
      const last = parseFloat(msg.c)
      const open = parseFloat(msg.o)
      onTick({ symbol, last, changePct: open ? ((last - open) / open) * 100 : 0 })
    })
  }
}

import type { Candle, DataAdapter, SymbolInfo, Ticker, Timeframe, Trade, TradeSource } from './types'

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

function toTrade(r: RawAgg): Trade {
  return { time: r.T, price: parseFloat(r.p), qty: parseFloat(r.q), buyerMaker: r.m }
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

/** Binance caps aggTrades at 1000 rows per request. */
const AGG_PAGE = 1000

interface RawAgg {
  a: number // aggregate trade id
  p: string // price
  q: string // quantity
  T: number // timestamp
  m: boolean // buyer was the maker
}

export class BinanceAdapter implements DataAdapter, TradeSource {
  id = 'binance'
  name = 'Binance'
  private exchangeInfo: Promise<any> | null = null
  private symbolsCache: Promise<SymbolInfo[]> | null = null
  private tickCache: Promise<Map<string, number>> | null = null

  static async available(timeoutMs = 3000): Promise<boolean> {
    try {
      const res = await fetch(`${REST}/ping`, { signal: AbortSignal.timeout(timeoutMs) })
      return res.ok
    } catch {
      return false
    }
  }

  private info(): Promise<any> {
    this.exchangeInfo ??= fetch(`${REST}/exchangeInfo`).then((r) => r.json())
    return this.exchangeInfo
  }

  private allSymbols(): Promise<SymbolInfo[]> {
    this.symbolsCache ??= this.info()
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

  /** PRICE_FILTER tick size per symbol, from the cached exchangeInfo payload. */
  async priceTick(symbol: string): Promise<number | null> {
    this.tickCache ??= this.info().then((j) => {
      const m = new Map<string, number>()
      for (const s of j.symbols as any[]) {
        const f = (s.filters as any[])?.find((x) => x.filterType === 'PRICE_FILTER')
        const tick = f ? parseFloat(f.tickSize) : NaN
        if (isFinite(tick) && tick > 0) m.set(s.symbol, tick)
      }
      return m
    })
    return (await this.tickCache).get(symbol) ?? null
  }

  /**
   * Walk aggTrades backwards from the latest print. Paging by id (rather than
   * by time) is the only way to read a busy symbol without silent truncation:
   * a time-windowed request returns the *first* 1000 trades in the window and
   * quietly drops the rest.
   */
  async fetchRecentTrades(symbol: string, since: number, cap: number): Promise<Trade[]> {
    const pages: Trade[][] = []
    let collected = 0

    const head = await fetch(`${REST}/aggTrades?symbol=${symbol}&limit=${AGG_PAGE}`)
    if (!head.ok) throw new Error(`Binance aggTrades ${head.status}`)
    let page = (await head.json()) as RawAgg[]

    while (page.length > 0) {
      pages.push(page.map(toTrade))
      collected += page.length
      const firstId = page[0].a
      if (collected >= cap || page[0].T <= since || firstId <= 0) break
      const fromId = Math.max(0, firstId - AGG_PAGE)
      const limit = firstId - fromId
      if (limit <= 0) break
      const res = await fetch(`${REST}/aggTrades?symbol=${symbol}&fromId=${fromId}&limit=${limit}`)
      if (!res.ok) break // partial history is still usable
      page = (await res.json()) as RawAgg[]
    }

    pages.reverse()
    return pages.flat()
  }

  subscribeTrades(symbol: string, onTrade: (t: Trade) => void): () => void {
    return persistentSocket(`${WS}/${symbol.toLowerCase()}@aggTrade`, (msg) => {
      if (!msg?.p) return
      onTrade(toTrade(msg as RawAgg))
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

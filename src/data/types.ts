export interface Candle {
  time: number // bucket open time, ms epoch
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export type Timeframe = '1m' | '5m' | '15m' | '1h' | '4h' | '1d' | '1w'

export const TIMEFRAMES: Timeframe[] = ['1m', '5m', '15m', '1h', '4h', '1d', '1w']

export const TF_MS: Record<Timeframe, number> = {
  '1m': 60_000,
  '5m': 300_000,
  '15m': 900_000,
  '1h': 3_600_000,
  '4h': 14_400_000,
  '1d': 86_400_000,
  '1w': 604_800_000,
}

export interface SymbolInfo {
  symbol: string
  base: string
  quote: string
  description?: string
}

export interface Ticker {
  symbol: string
  last: number
  changePct: number // vs 24h ago (or day open)
}

/**
 * Pluggable market-data source. Implement this interface to add a new
 * exchange/broker feed; the rest of the app only talks to this contract.
 */
export interface DataAdapter {
  id: string
  name: string
  searchSymbols(query: string): Promise<SymbolInfo[]>
  /** Most-recent `limit` candles, or candles ending strictly before `endTime` when given. */
  fetchCandles(symbol: string, tf: Timeframe, limit: number, endTime?: number): Promise<Candle[]>
  /** Live updates for the building candle. Returns an unsubscribe function. */
  subscribeCandles(symbol: string, tf: Timeframe, onCandle: (c: Candle) => void): () => void
  /** Lightweight last-price stream for watchlists. Returns an unsubscribe function. */
  subscribeTicker(symbol: string, onTick: (t: Ticker) => void): () => void
}

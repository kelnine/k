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

/** A single executed trade (Binance aggTrade, or a synthetic equivalent). */
export interface Trade {
  time: number // ms epoch
  price: number
  qty: number
  /** true when the buyer was the maker, i.e. an aggressive SELL that hit the bid */
  buyerMaker: boolean
}

/**
 * Optional tick-data capability. Adapters that can serve raw trades let the
 * app build footprint (orderflow) charts; adapters that can't simply omit it
 * and the UI falls back to candles.
 */
export interface TradeSource {
  /**
   * Recent trades in ascending time order, walking backwards from now until
   * `since` is covered or `cap` trades have been collected — whichever comes
   * first. Exchanges page tick data hard, so partial coverage is normal and
   * the caller is expected to drop bars the window doesn't reach.
   */
  fetchRecentTrades(symbol: string, since: number, cap: number): Promise<Trade[]>
  /** Live trade prints. Returns an unsubscribe function. */
  subscribeTrades(symbol: string, onTrade: (t: Trade) => void): () => void
  /** Exchange price increment, when the venue publishes one. */
  priceTick(symbol: string): Promise<number | null>
}

export function supportsTrades(a: DataAdapter): a is DataAdapter & TradeSource {
  const t = a as Partial<TradeSource>
  return typeof t.fetchRecentTrades === 'function' && typeof t.subscribeTrades === 'function'
}

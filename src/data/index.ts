import { BinanceAdapter } from './binance'
import { DemoAdapter } from './demo'
import type { DataAdapter } from './types'

export * from './types'

/**
 * Adapter registry. Live Binance data when reachable, otherwise the synthetic
 * demo feed so the app always works (offline, geo-blocked, etc.).
 */
export async function resolveAdapter(): Promise<DataAdapter> {
  if (await BinanceAdapter.available()) return new BinanceAdapter()
  return new DemoAdapter()
}

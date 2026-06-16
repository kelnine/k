import { fetchCandles, fetchPrice } from './market'
import { detectStructureBreaks } from './smc-signals'
import { toSignal } from './signals'
import { postTweet } from './twitter'
import { entryTweet } from './format'
import { loadState, saveState, markSeen, openTrade } from './state'
import { processTrades } from './trade-manager'
import type { BotState, Trade } from './types'
import { BOT_SYMBOLS, BOT_TF, BOT_POLL_MS, BOT_SWING, BOT_CANDLES } from './config'

const RECENCY_BARS = 3

async function scanSymbol(symbol: string, state: BotState): Promise<void> {
  const candles = await fetchCandles(symbol, BOT_TF, BOT_CANDLES)
  const breaks = detectStructureBreaks(candles, BOT_SWING)

  const recent = breaks.filter((b: ReturnType<typeof detectStructureBreaks>[0]) => b.breakBar >= candles.length - RECENCY_BARS)
  for (const sb of recent) {
    const signal = toSignal(symbol, BOT_TF, sb)
    if (state.seenSignalIds.includes(signal.id)) continue

    markSeen(state, signal.id)
    console.log(`  [SIGNAL] ${symbol} ${signal.breakType} ${signal.side} @ ${signal.level.toFixed(2)}`)

    try {
      const tweetId = await postTweet(entryTweet(signal))
      const trade: Trade = {
        signal,
        tweetId,
        openedAt: new Date().toISOString(),
        t1Hit: false,
        t2Hit: false,
        t3Hit: false,
        exitPrice: null,
        exitReason: null,
        closed: false,
      }
      openTrade(state, trade)
    } catch (e) {
      console.error(`  Entry tweet failed (${symbol}):`, e)
    }
  }
}

async function tick(): Promise<void> {
  const now = new Date().toISOString()
  console.log(`\n[${now}] tick`)
  const state = loadState()

  const prices = new Map<string, number>()
  await Promise.allSettled(
    BOT_SYMBOLS.map(async (sym: string) => {
      prices.set(sym, await fetchPrice(sym))
    }),
  )

  await processTrades(state, prices)

  for (const sym of BOT_SYMBOLS) {
    try {
      await scanSymbol(sym, state)
    } catch (e) {
      console.error(`  Scan error (${sym}):`, e)
    }
  }

  saveState(state)
  console.log(`  open trades: ${state.openTrades.length}`)
}

async function main(): Promise<void> {
  console.log('KCharts Twitter Bot')
  console.log('Symbols :', BOT_SYMBOLS.join(', '))
  console.log('Timeframe:', BOT_TF)
  console.log('Interval :', BOT_POLL_MS, 'ms')
  console.log('Dry run  :', process.env.BOT_DRY_RUN !== 'false')
  console.log()

  await tick()
  setInterval(() => {
    tick().catch(console.error)
  }, BOT_POLL_MS)
}

main().catch(console.error)

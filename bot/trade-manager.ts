import type { BotState, Trade } from './types'
import { postTweet } from './twitter'
import { targetHitTweet, exitTweet } from './format'
import { closeTrade, saveState } from './state'

export async function processTrades(state: BotState, prices: Map<string, number>): Promise<void> {
  for (const trade of [...state.openTrades]) {
    if (trade.closed) continue
    const price = prices.get(trade.signal.symbol)
    if (price === undefined) continue

    const { signal } = trade
    const bull = signal.side === 'bull'

    // T1
    if (!trade.t1Hit && (bull ? price >= signal.t1 : price <= signal.t1)) {
      trade.t1Hit = true
      try {
        trade.t1TweetId = await postTweet(targetHitTweet(trade, 't1'), trade.tweetId)
      } catch (e) {
        console.error('T1 tweet error:', e)
      }
    }

    // T2
    if (trade.t1Hit && !trade.t2Hit && (bull ? price >= signal.t2 : price <= signal.t2)) {
      trade.t2Hit = true
      try {
        trade.t2TweetId = await postTweet(
          targetHitTweet(trade, 't2'),
          trade.t1TweetId ?? trade.tweetId,
        )
      } catch (e) {
        console.error('T2 tweet error:', e)
      }
    }

    // T3 → full exit
    if (trade.t2Hit && !trade.t3Hit && (bull ? price >= signal.t3 : price <= signal.t3)) {
      await closeOut(state, trade, signal.t3, 't3', trade.t2TweetId ?? trade.tweetId)
      continue
    }

    // stop hit
    if (bull ? price <= signal.stop : price >= signal.stop) {
      await closeOut(state, trade, signal.stop, 'stop', trade.tweetId)
    }
  }
}

async function closeOut(
  state: BotState,
  trade: Trade,
  exitPrice: number,
  reason: 't3' | 'stop',
  replyTo: string,
): Promise<void> {
  if (reason === 't3') trade.t3Hit = true
  trade.exitPrice = exitPrice
  trade.exitReason = reason
  trade.closed = true
  try {
    trade.exitTweetId = await postTweet(exitTweet(trade, exitPrice, reason), replyTo)
  } catch (e) {
    console.error('Exit tweet error:', e)
  }
  closeTrade(state, trade)
  saveState(state)
}

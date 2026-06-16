import { readFileSync, writeFileSync, existsSync } from 'fs'
import type { BotState, Trade } from './types'
import { BOT_STATE_FILE } from './config'

const EMPTY: BotState = { seenSignalIds: [], openTrades: [], closedTrades: [] }

export function loadState(): BotState {
  try {
    if (!existsSync(BOT_STATE_FILE)) return structuredClone(EMPTY)
    return JSON.parse(readFileSync(BOT_STATE_FILE, 'utf8')) as BotState
  } catch {
    return structuredClone(EMPTY)
  }
}

export function saveState(state: BotState): void {
  writeFileSync(BOT_STATE_FILE, JSON.stringify(state, null, 2))
}

export function markSeen(state: BotState, id: string): void {
  if (!state.seenSignalIds.includes(id)) {
    state.seenSignalIds.push(id)
    if (state.seenSignalIds.length > 2000) state.seenSignalIds.splice(0, state.seenSignalIds.length - 2000)
  }
}

export function openTrade(state: BotState, trade: Trade): void {
  state.openTrades.push(trade)
}

export function closeTrade(state: BotState, trade: Trade): void {
  const idx = state.openTrades.indexOf(trade)
  if (idx >= 0) state.openTrades.splice(idx, 1)
  state.closedTrades.push(trade)
  if (state.closedTrades.length > 200) state.closedTrades.splice(0, state.closedTrades.length - 200)
}

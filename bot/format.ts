import type { Signal, Trade } from './types'
import { BOT_HASHTAGS } from './config'

function p(n: number): string {
  const decimals = n >= 1000 ? 2 : n >= 1 ? 4 : 6
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

function ts(): string {
  return new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function setupLabel(signal: Signal): string {
  const dir = signal.side === 'bull' ? 'Bullish' : 'Bearish'
  return `${signal.breakType} ${dir}`
}

export function entryTweet(signal: Signal): string {
  const dir = signal.side === 'bull' ? '📈 LONG' : '📉 SHORT'
  const base = signal.symbol.replace(/USDT$/, '')
  const setup = setupLabel(signal)

  return [
    `${ts()}  ${dir}  $${base} @ ${p(signal.entry)}`,
    `Stop: ${p(signal.stop)} | T1: ${p(signal.t1)}  T2: ${p(signal.t2)}  T3: ${p(signal.t3)}`,
    ``,
    `Setup: ${setup} | TF: ${signal.tf} | Level: ${p(signal.level)}`,
    `OB zone: ${p(signal.obBottom)} – ${p(signal.obTop)}`,
    ``,
    BOT_HASHTAGS,
  ].join('\n')
}

export function targetHitTweet(trade: Trade, target: 't1' | 't2' | 't3'): string {
  const base = trade.signal.symbol.replace(/USDT$/, '')
  const price = target === 't1' ? trade.signal.t1 : target === 't2' ? trade.signal.t2 : trade.signal.t3
  const label = target.toUpperCase()

  const t1s = trade.t1Hit ? '✅ T1' : '– T1'
  const t2s = trade.t2Hit ? '✅ T2' : '– T2'
  const t3s = trade.t3Hit ? '✅ T3' : '– T3'

  return [
    `✅ ${label} HIT — $${base} @ ${p(price)}`,
    `${t1s}  ${t2s}  ${t3s}`,
    `Entry: ${p(trade.signal.entry)} | Stop: ${p(trade.signal.stop)}`,
  ].join('\n')
}

export function exitTweet(trade: Trade, exitPrice: number, reason: 't3' | 'stop'): string {
  const sig = trade.signal
  const base = sig.symbol.replace(/USDT$/, '')
  const risk = Math.abs(sig.entry - sig.stop)
  const pnl = sig.side === 'bull' ? exitPrice - sig.entry : sig.entry - exitPrice
  const pnlPct = (pnl / sig.entry) * 100
  const rMultiple = pnl / risk
  const isWin = pnl > 0
  const result = isWin ? 'WIN ✅' : 'LOSS ❌'
  const sign = pnl >= 0 ? '+' : ''

  const t1s = trade.t1Hit ? '✅ T1' : '– T1'
  const t2s = trade.t2Hit ? '✅ T2' : '– T2'
  const t3s = trade.t3Hit ? '✅ T3' : '– T3'

  const setup = setupLabel(sig)
  const closeReason = reason === 't3' ? 'T3 reached' : 'Stop hit'

  return [
    `📊 $${base} — ${setup} | ${result}`,
    ``,
    `Entry: ${p(sig.entry)}  Stop: ${p(sig.stop)}  Exit: ${p(exitPrice)}`,
    `${t1s}  ${t2s}  ${t3s}`,
    ``,
    `${sign}${pnlPct.toFixed(2)}%  (${sign}${rMultiple.toFixed(2)}R)  — ${closeReason}`,
    ``,
    BOT_HASHTAGS,
  ].join('\n')
}

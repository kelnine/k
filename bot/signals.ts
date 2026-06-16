import type { StructureBreak } from './smc-signals'
import type { Signal } from './types'
import { BOT_T1_R, BOT_T2_R, BOT_T3_R } from './config'

const ENTRY_BUFFER = 0.0005

export function toSignal(symbol: string, tf: string, sb: StructureBreak): Signal {
  const { side, level, breakBar, obTop, obBottom, breakType } = sb

  let entry: number
  let stop: number

  if (side === 'bull') {
    entry = level * (1 + ENTRY_BUFFER)
    stop = obBottom * (1 - ENTRY_BUFFER)
  } else {
    entry = level * (1 - ENTRY_BUFFER)
    stop = obTop * (1 + ENTRY_BUFFER)
  }

  const risk = Math.abs(entry - stop)
  const dir = side === 'bull' ? 1 : -1

  const t1 = entry + dir * BOT_T1_R * risk
  const t2 = entry + dir * BOT_T2_R * risk
  const t3 = entry + dir * BOT_T3_R * risk

  const id = `${symbol}:${side}:${level.toFixed(4)}:${breakBar}:${tf}`

  return {
    id,
    symbol,
    tf,
    side,
    breakType,
    level,
    entry,
    stop,
    t1,
    t2,
    t3,
    obTop,
    obBottom,
    breakBar,
    detectedAt: new Date().toISOString(),
  }
}

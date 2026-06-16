import type { Candle } from '../src/data/types'

export interface StructureBreak {
  breakBar: number
  level: number
  side: 'bull' | 'bear'
  breakType: 'BOS' | 'CHoCH'
  obIdx: number
  obTop: number
  obBottom: number
}

interface Swing {
  idx: number
  price: number
  kind: 'H' | 'L'
  confirm: number
}

function detectSwings(candles: Candle[], L: number): Swing[] {
  const n = candles.length
  const swings: Swing[] = []
  for (let i = L; i < n - L; i++) {
    let isH = true
    let isL = true
    for (let k = 1; k <= L; k++) {
      const h = candles[i].high
      const l = candles[i].low
      if (!(h > candles[i - k].high && h >= candles[i + k].high)) isH = false
      if (!(l < candles[i - k].low && l <= candles[i + k].low)) isL = false
      if (!isH && !isL) break
    }
    if (isH) swings.push({ idx: i, price: candles[i].high, kind: 'H', confirm: i + L })
    if (isL) swings.push({ idx: i, price: candles[i].low, kind: 'L', confirm: i + L })
  }
  return swings
}

function lastBullOB(candles: Candle[], fromIdx: number, t: number): number | null {
  for (let j = t - 1; j >= Math.max(0, fromIdx - 1); j--) {
    if (candles[j].close < candles[j].open) return j
  }
  return null
}

function lastBearOB(candles: Candle[], fromIdx: number, t: number): number | null {
  for (let j = t - 1; j >= Math.max(0, fromIdx - 1); j--) {
    if (candles[j].close > candles[j].open) return j
  }
  return null
}

export function detectStructureBreaks(candles: Candle[], L = 5): StructureBreak[] {
  const n = candles.length
  if (n < L * 2 + 3) return []

  const swings = detectSwings(candles, L)
  const confirmAt: Swing[][] = Array.from({ length: n }, () => [])
  for (const s of swings) if (s.confirm < n) confirmAt[s.confirm].push(s)

  const breaks: StructureBreak[] = []
  let trend = 0
  let lastH: Swing | null = null
  let lastL: Swing | null = null
  let crossedH = false
  let crossedL = false

  for (let t = 0; t < n; t++) {
    for (const s of confirmAt[t]) {
      if (s.kind === 'H') {
        lastH = s
        crossedH = false
      } else {
        lastL = s
        crossedL = false
      }
    }
    const close = candles[t].close
    if (lastH && !crossedH && close > lastH.price) {
      const breakType = trend === -1 ? 'CHoCH' : 'BOS'
      const obIdx = lastBullOB(candles, lastH.idx, t)
      if (obIdx !== null) {
        breaks.push({
          breakBar: t,
          level: lastH.price,
          side: 'bull',
          breakType,
          obIdx,
          obTop: candles[obIdx].high,
          obBottom: candles[obIdx].low,
        })
      }
      crossedH = true
      trend = 1
    }
    if (lastL && !crossedL && close < lastL.price) {
      const breakType = trend === 1 ? 'CHoCH' : 'BOS'
      const obIdx = lastBearOB(candles, lastL.idx, t)
      if (obIdx !== null) {
        breaks.push({
          breakBar: t,
          level: lastL.price,
          side: 'bear',
          breakType,
          obIdx,
          obTop: candles[obIdx].high,
          obBottom: candles[obIdx].low,
        })
      }
      crossedL = true
      trend = -1
    }
  }

  return breaks
}

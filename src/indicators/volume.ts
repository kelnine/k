import type { Candle } from '../data/types'
import type { IndicatorDef } from './index'
import { formatCompact } from '../engine/utils'

/**
 * Volume Analysis — a from-scratch volume-profiling pane that reproduces the
 * "volume dashboard" trading system: a relative-volume histogram plus a moving
 * average, and a HUD of derived metrics (relative volume, volume %, consecutive
 * run, consistency, pattern, trend and a composite signal) read off the most
 * recent bar. No external libraries — pure functions over the candle series.
 */

const MA_LEN = 20 // baseline volume window
const CONSISTENCY_LEN = 20 // window for the coefficient-of-variation read
const TREND_LEN = 8 // window for the volume-trend slope

const COL = {
  vol: '#26a69a',
  ma: '#ff9800',
  hi: '#26c6da', // above-average volume
  lo: '#5c6f7a', // below-average volume
  up: '#26a69a',
  down: '#ef5350',
  mute: '#9aa7b2',
  warn: '#fdd835',
}

function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= n) sum -= values[i - n]
    if (i >= n - 1) out[i] = sum / n
  }
  return out
}

export function makeVolume(): IndicatorDef {
  return {
    id: 'volana',
    name: 'Volume Analysis',
    kind: 'pane',
    compute(candles: Candle[]) {
      const vols = candles.map((c) => c.volume)
      const volMA = sma(vols, MA_LEN)
      const n = candles.length

      // ---- legend metrics from the most recent bar ----
      const items: { color: string; value: string }[] = []
      if (n > 0) {
        const i = n - 1
        const c = candles[i]
        const vol = c.volume
        const ma = volMA[i] ?? vol
        const relVol = ma > 0 ? vol / ma : 1
        const volPct = (relVol - 1) * 100

        // consecutive bars moving the same direction in volume as the last step
        let consec = 0
        if (i > 0) {
          const dir = Math.sign(vols[i] - vols[i - 1])
          if (dir !== 0) {
            consec = 1
            for (let k = i - 1; k > 0; k--) {
              if (Math.sign(vols[k] - vols[k - 1]) === dir) consec++
              else break
            }
          }
        }

        // consistency: coefficient of variation of recent volume
        const from = Math.max(0, n - CONSISTENCY_LEN)
        const win = vols.slice(from)
        const mean = win.reduce((s, v) => s + v, 0) / (win.length || 1)
        const variance = win.reduce((s, v) => s + (v - mean) ** 2, 0) / (win.length || 1)
        const cv = mean > 0 ? Math.sqrt(variance) / mean : 0
        const consistency = cv < 0.4 ? 'CONSISTENT' : cv < 0.9 ? 'MODERATE' : 'ERRATIC'

        // pattern: classify the current bar against its average
        const pattern =
          relVol >= 2 ? 'Volume Spike'
          : relVol >= 1.3 ? 'High Volume'
          : relVol <= 0.5 ? 'Low Volume'
          : 'Normal'

        // trend: slope of the volume MA over the trend window
        let trend = 'Flat'
        const maNow = volMA[i]
        const maPast = volMA[Math.max(0, i - TREND_LEN)]
        if (maNow != null && maPast != null && maPast > 0) {
          const slope = (maNow - maPast) / maPast
          trend = slope > 0.1 ? 'Increasing' : slope < -0.1 ? 'Decreasing' : 'Flat'
        }

        // composite signal: combine relative volume with price direction
        const priceUp = c.close >= c.open
        let signal = 'MONITOR'
        if (relVol >= 2) signal = priceUp ? 'STRONG BUY' : 'STRONG SELL'
        else if (relVol >= 1.3) signal = priceUp ? 'ACCUMULATE' : 'DISTRIBUTION'
        else if (relVol <= 0.5) signal = 'MONITOR'
        else signal = priceUp ? 'BULLISH' : 'BEARISH'

        const relColor = relVol >= 1.3 ? COL.hi : relVol <= 0.5 ? COL.lo : COL.mute
        const pctColor = volPct >= 0 ? COL.up : COL.down
        const consistColor = consistency === 'CONSISTENT' ? COL.up : consistency === 'ERRATIC' ? COL.down : COL.warn
        const trendColor = trend === 'Increasing' ? COL.up : trend === 'Decreasing' ? COL.down : COL.mute
        const signalColor =
          signal.includes('BUY') || signal === 'ACCUMULATE' || signal === 'BULLISH' ? COL.up
          : signal.includes('SELL') || signal === 'DISTRIBUTION' || signal === 'BEARISH' ? COL.down
          : COL.warn

        items.push(
          { color: COL.vol, value: `Vol ${formatCompact(vol)}` },
          { color: COL.ma, value: `MA ${formatCompact(ma)}` },
          { color: relColor, value: `RelVol ${relVol.toFixed(2)}×` },
          { color: pctColor, value: `${volPct >= 0 ? '+' : ''}${volPct.toFixed(1)}%` },
          { color: COL.mute, value: `Consec ${consec} bars` },
          { color: consistColor, value: consistency },
          { color: relColor, value: pattern },
          { color: trendColor, value: trend },
          { color: signalColor, value: `▸ ${signal}` },
        )
      }

      return {
        plots: [
          { key: 'vol', color: COL.vol, style: 'hist', values: vols },
          { key: 'ma', color: COL.ma, style: 'line', width: 1.5, values: volMA },
        ],
        legend: items,
      }
    },
  }
}

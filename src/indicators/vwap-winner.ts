import type { Candle } from '../data/types'
import type { IndicatorDef, IndicatorShape, Plot } from './index'

/**
 * VWAP Winner — daily-anchored VWAP with volume-weighted standard-deviation
 * bands and mean-reversion signals.
 *
 * Layout matches the classic "winning VWAP" setup:
 *   - solid yellow centerline: session VWAP
 *   - dashed green bands above (+1σ / +2σ / +3σ): SELL / take-profit zone
 *   - dashed lavender bands below (−1σ / −2σ / −3σ): BUY / accumulation zone
 *
 * Signals fire on ±2σ band rejections: a BUY when a candle wicks below the
 * −2σ band but closes back above it, a SELL when it wicks above +2σ and
 * closes back under. A short cooldown stops back-to-back markers, and no
 * signal fires in the first few bars of a session while the bands are still
 * finding their width.
 */

const VWAP_COLOR = '#ffee33'
const UPPER_COLOR = '#4caf50'
const LOWER_COLOR = '#b39ddb'
const BUY_COLOR = '#26a69a'
const SELL_COLOR = '#ef5350'

const COOLDOWN_BARS = 5
const MIN_SESSION_BARS = 3

export function makeVwapWinner(): IndicatorDef {
  return {
    id: 'vwapwin',
    name: 'VWAP Winner',
    kind: 'overlay',
    compute(candles: Candle[]) {
      const n = candles.length
      const vwap: (number | null)[] = new Array(n).fill(null)
      const bands: (number | null)[][] = Array.from({ length: 6 }, () => new Array(n).fill(null))
      // bands[0..2] = +1σ..+3σ, bands[3..5] = −1σ..−3σ

      let day = -1
      let pv = 0
      let pv2 = 0
      let vol = 0
      let sessionBars = 0

      const shapes: IndicatorShape[] = []
      let lastSignal = -Infinity
      let lastSignalText = ''

      for (let i = 0; i < n; i++) {
        const c = candles[i]
        const d = Math.floor(c.time / 86_400_000)
        if (d !== day) {
          day = d
          pv = 0
          pv2 = 0
          vol = 0
          sessionBars = 0
        }
        sessionBars++
        const typical = (c.high + c.low + c.close) / 3
        pv += typical * c.volume
        pv2 += typical * typical * c.volume
        vol += c.volume
        if (vol <= 0) continue

        const mean = pv / vol
        const sd = Math.sqrt(Math.max(0, pv2 / vol - mean * mean))
        vwap[i] = mean
        for (let k = 1; k <= 3; k++) {
          bands[k - 1][i] = mean + k * sd
          bands[k + 2][i] = mean - k * sd
        }

        if (sd <= 0 || sessionBars < MIN_SESSION_BARS || i - lastSignal <= COOLDOWN_BARS) continue
        const lower2 = mean - 2 * sd
        const upper2 = mean + 2 * sd
        if (c.low <= lower2 && c.close > lower2) {
          shapes.push({ type: 'marker', x: i, y: c.low, text: '▲ BUY', color: BUY_COLOR, place: 'below' })
          lastSignal = i
          lastSignalText = '▲ BUY'
        } else if (c.high >= upper2 && c.close < upper2) {
          shapes.push({ type: 'marker', x: i, y: c.high, text: '▼ SELL', color: SELL_COLOR, place: 'above' })
          lastSignal = i
          lastSignalText = '▼ SELL'
        }
      }

      const plots: Plot[] = [
        { key: 'vwap', color: VWAP_COLOR, style: 'line', width: 2, values: vwap },
        { key: 'up1', color: UPPER_COLOR, style: 'line', dash: [4, 4], values: bands[0] },
        { key: 'up2', color: UPPER_COLOR, style: 'line', dash: [4, 4], values: bands[1] },
        { key: 'up3', color: UPPER_COLOR, style: 'line', dash: [4, 4], values: bands[2] },
        { key: 'dn1', color: LOWER_COLOR, style: 'line', dash: [4, 4], values: bands[3] },
        { key: 'dn2', color: LOWER_COLOR, style: 'line', dash: [4, 4], values: bands[4] },
        { key: 'dn3', color: LOWER_COLOR, style: 'line', dash: [4, 4], values: bands[5] },
      ]

      // live read-out: where price sits relative to the bands right now
      const legend: { color: string; value: string }[] = []
      const last = candles[n - 1]
      const v = n > 0 ? vwap[n - 1] : null
      if (last && v !== null) {
        const up1 = bands[0][n - 1]
        const dn1 = bands[3][n - 1]
        legend.push({ color: VWAP_COLOR, value: `VWAP ${v.toPrecision(6)}` })
        if (up1 !== null && last.close >= up1) {
          legend.push({ color: SELL_COLOR, value: 'SELL zone' })
        } else if (dn1 !== null && last.close <= dn1) {
          legend.push({ color: BUY_COLOR, value: 'BUY zone' })
        } else {
          legend.push({
            color: last.close >= v ? BUY_COLOR : SELL_COLOR,
            value: last.close >= v ? 'above VWAP' : 'below VWAP',
          })
        }
        if (lastSignalText) {
          legend.push({
            color: lastSignalText.includes('BUY') ? BUY_COLOR : SELL_COLOR,
            value: `last: ${lastSignalText}`,
          })
        }
      }

      return { plots, shapes, legend }
    },
  }
}

import type { Candle } from '../data/types'
import { formatPrice } from '../engine/utils'
import type { IndicatorDef, IndicatorResult } from './index'

/**
 * Visible-range volume profile (VPVR).
 *
 * Volume is bucketed by price rather than by time: each candle's volume is
 * spread across the price rows its high–low range covers, split into "up"
 * (close ≥ open) and "down" volume. The result is the horizontal histogram
 * on the left of the pane, with the point of control (heaviest row) and the
 * value area — the band around the POC holding `VALUE_AREA` of all volume.
 *
 * Unlike every other indicator here, this one depends on what is on screen,
 * so it is flagged `visibleRange` and the engine recomputes it while panning.
 */

export interface ProfileRow {
  low: number
  high: number
  up: number
  down: number
}

export interface VolumeProfile {
  rows: ProfileRow[]
  /** price at the centre of the heaviest row */
  poc: number
  /** value area high / low */
  vah: number
  val: number
  /** volume of the heaviest row, for scaling bar widths */
  maxRowVolume: number
  total: number
}

const ROWS = 80
const VALUE_AREA = 0.7

export function computeProfile(candles: Candle[], from: number, to: number): VolumeProfile | null {
  if (from > to || to >= candles.length || from < 0) return null

  let lo = Infinity
  let hi = -Infinity
  for (let i = from; i <= to; i++) {
    lo = Math.min(lo, candles[i].low)
    hi = Math.max(hi, candles[i].high)
  }
  if (!isFinite(lo) || !isFinite(hi)) return null
  if (hi === lo) hi = lo * 1.0001 + 1e-9

  const step = (hi - lo) / ROWS
  const rows: ProfileRow[] = Array.from({ length: ROWS }, (_, r) => ({
    low: lo + r * step,
    high: lo + (r + 1) * step,
    up: 0,
    down: 0,
  }))

  for (let i = from; i <= to; i++) {
    const c = candles[i]
    const span = c.high - c.low
    const first = Math.max(0, Math.min(ROWS - 1, Math.floor((c.low - lo) / step)))
    const last = Math.max(0, Math.min(ROWS - 1, Math.floor((c.high - lo) / step)))
    const up = c.close >= c.open
    for (let r = first; r <= last; r++) {
      // volume weighted by how much of the candle's range falls in this row
      const overlap =
        span <= 0
          ? 1
          : (Math.min(c.high, rows[r].high) - Math.max(c.low, rows[r].low)) / span
      if (overlap <= 0) continue
      const v = c.volume * overlap
      if (up) rows[r].up += v
      else rows[r].down += v
    }
  }

  const vol = rows.map((r) => r.up + r.down)
  const total = vol.reduce((a, b) => a + b, 0)
  if (total === 0) return null

  let pocIdx = 0
  for (let r = 1; r < ROWS; r++) if (vol[r] > vol[pocIdx]) pocIdx = r

  // grow the value area outward from the POC, always taking the heavier side
  let lower = pocIdx
  let upper = pocIdx
  let acc = vol[pocIdx]
  const target = total * VALUE_AREA
  while (acc < target && (lower > 0 || upper < ROWS - 1)) {
    const below = lower > 0 ? vol[lower - 1] : -1
    const above = upper < ROWS - 1 ? vol[upper + 1] : -1
    if (above >= below) acc += vol[++upper]
    else acc += vol[--lower]
  }

  return {
    rows,
    poc: (rows[pocIdx].low + rows[pocIdx].high) / 2,
    vah: rows[upper].high,
    val: rows[lower].low,
    maxRowVolume: vol[pocIdx],
    total,
  }
}

export function makeVolumeProfile(): IndicatorDef {
  return {
    id: 'vp',
    name: 'Volume Profile',
    kind: 'overlay',
    visibleRange: true,
    compute(candles, from, to): IndicatorResult {
      const a = from ?? 0
      const b = to ?? candles.length - 1
      const profile = computeProfile(candles, a, b)
      if (!profile) return { plots: [] }
      return {
        plots: [],
        profile,
        legend: [
          { color: '#d1d4dc', value: `POC ${formatPrice(profile.poc)}` },
          { color: '#26a69a', value: `VAH ${formatPrice(profile.vah)}` },
          { color: '#ff9800', value: `VAL ${formatPrice(profile.val)}` },
        ],
      }
    },
  }
}

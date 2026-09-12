import type { Candle } from '../data/types'

/**
 * Goldbach levels over power-of-three dealing ranges.
 *
 * A PO3 range is a block of price 3^k units tall, anchored to multiples of its
 * own size — so for a 81-point range on NQ the boundaries sit at 29322 / 29403,
 * not wherever the last swing happened to print. Because 243 = 3 × 81 the
 * ranges nest: every larger range's boundary is also a smaller one's.
 *
 * Inside a range, price is partitioned at fixed ratios, each standing for the
 * dealing-range structure the algorithm is expected to leave there:
 *
 *   0.03 / 0.97  RB  rejection block
 *   0.11 / 0.89  OB  order block
 *   0.17 / 0.83  FV  fair value gap
 *   0.29 / 0.71  LV  liquidity void
 *   0.41 / 0.59  BR  breaker
 *   0.47 / 0.53  MB  mitigation block
 *   0.50         EQ  equilibrium — premium above, discount below
 *
 * plus the -0.111 / 1.111 extensions either side of the range.
 *
 * Everything here is pure arithmetic on the current price: no swings, no
 * lookback, nothing to confirm. The levels for a given price are the same
 * levels for everyone looking at the same instrument.
 */

export type GoldbachRole = 'Low' | 'RB' | 'OB' | 'FV' | 'LV' | 'BR' | 'MB' | 'EQ' | 'High' | 'Ext'

export interface GoldbachLevel {
  ratio: number
  role: GoldbachRole
  price: number
  /** the PO3 size this level belongs to */
  size: number
  /** 'premium' above equilibrium, 'discount' below, 'eq' at it */
  zone: 'premium' | 'discount' | 'eq'
  label: string
}

export interface Po3Range {
  size: number
  low: number
  high: number
  eq: number
  levels: GoldbachLevel[]
}

const PARTITION: { ratio: number; role: GoldbachRole }[] = [
  { ratio: 0, role: 'Low' },
  { ratio: 0.03, role: 'RB' },
  { ratio: 0.11, role: 'OB' },
  { ratio: 0.17, role: 'FV' },
  { ratio: 0.29, role: 'LV' },
  { ratio: 0.41, role: 'BR' },
  { ratio: 0.47, role: 'MB' },
  { ratio: 0.5, role: 'EQ' },
  { ratio: 0.53, role: 'MB' },
  { ratio: 0.59, role: 'BR' },
  { ratio: 0.71, role: 'LV' },
  { ratio: 0.83, role: 'FV' },
  { ratio: 0.89, role: 'OB' },
  { ratio: 0.97, role: 'RB' },
  { ratio: 1, role: 'High' },
]

const EXTENSIONS = [-0.111, 1.111]

/** The levels an algorithm is expected to trade *from*, in order of interest. */
export const ENTRY_ROLES: GoldbachRole[] = ['OB', 'FV', 'RB', 'LV']

function ratioLabel(r: number): string {
  if (r === 0) return '0 Low'
  if (r === 1) return '1 High'
  if (r === 0.5) return '0.5 EQ'
  return r.toFixed(2).replace(/0$/, '').replace(/\.$/, '')
}

/** Powers of three spanning everything from sub-cent alts to index futures. */
export function po3Sizes(): number[] {
  const out: number[] = []
  for (let k = -6; k <= 12; k++) out.push(Math.pow(3, k))
  return out
}

/**
 * Pick the PO3 size that frames this instrument's movement: the smallest one
 * that comfortably contains a typical bar's range, so price works through the
 * partition over hours rather than crossing the whole range in one candle.
 */
export function chooseSize(candles: Candle[], mult = 1.2): number {
  const from = Math.max(1, candles.length - 100)
  const ranges: number[] = []
  for (let i = from; i < candles.length; i++) {
    const c = candles[i]
    const pc = candles[i - 1].close
    ranges.push(Math.max(c.high - c.low, Math.abs(c.high - pc), Math.abs(c.low - pc)))
  }
  if (ranges.length === 0) return 1
  ranges.sort((a, b) => a - b)
  const median = ranges[Math.floor(ranges.length / 2)]
  const target = median * mult
  for (const s of po3Sizes()) if (s >= target) return s
  return po3Sizes()[po3Sizes().length - 1]
}

/** The PO3 range of `size` that currently contains `price`. */
export function po3Range(price: number, size: number): Po3Range {
  const low = Math.floor(price / size) * size
  const high = low + size
  const eq = low + size / 2
  const levels: GoldbachLevel[] = PARTITION.map(({ ratio, role }) => ({
    ratio,
    role,
    price: low + size * ratio,
    size,
    zone: ratio > 0.5 ? 'premium' : ratio < 0.5 ? 'discount' : 'eq',
    label: `${ratioLabel(ratio)} | ${fmtSize(size)}`,
  }))
  for (const ratio of EXTENSIONS) {
    levels.push({
      ratio,
      role: 'Ext',
      price: low + size * ratio,
      size,
      zone: ratio > 0.5 ? 'premium' : 'discount',
      label: `${ratio} Ext | ${fmtSize(size)}`,
    })
  }
  return { size, low, high, eq, levels }
}

function fmtSize(size: number): string {
  return size >= 1 ? String(Math.round(size)) : size.toPrecision(2)
}

/** Where price sits inside its range: 0 at the low, 1 at the high. */
export function rangePosition(price: number, r: Po3Range): number {
  return (price - r.low) / r.size
}

/** Nearest level to `price`, optionally restricted to a side and to roles. */
export function nearestLevel(
  price: number,
  r: Po3Range,
  opts: { side?: 'above' | 'below'; roles?: GoldbachRole[] } = {},
): GoldbachLevel | null {
  let best: GoldbachLevel | null = null
  let bestGap = Infinity
  for (const l of r.levels) {
    if (opts.roles && !opts.roles.includes(l.role)) continue
    if (opts.side === 'above' && l.price <= price) continue
    if (opts.side === 'below' && l.price >= price) continue
    const gap = Math.abs(l.price - price)
    if (gap < bestGap) {
      bestGap = gap
      best = l
    }
  }
  return best
}

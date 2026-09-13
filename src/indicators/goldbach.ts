import type { Candle } from '../data/types'
import { chooseSize, po3Range, rangePosition, ENTRY_ROLES, nearestLevel, type GoldbachLevel, type Po3Range } from '../model/goldbach'
import type { IndicatorDef, IndicatorResult, IndicatorShape } from './index'

/**
 * Goldbach PO3 levels on the chart.
 *
 * Two nested dealing ranges are drawn at once — the one sized to this
 * instrument's bar range and the one three times larger, exactly the way an
 * 81-point and a 243-point range nest on NQ. Each level is labelled with its
 * ratio, the structure it stands for, and which range it belongs to
 * (`0.83 FV | 81`), and the right-hand gutter carries the premium/discount
 * column for the smaller range: red above equilibrium, green below.
 */

const C = {
  level: '255,193,7',
  strong: '255,152,0',
  eq: '120,144,180',
  ext: '171,71,188',
  premium: '239,83,80',
  discount: '38,166,154',
}

/** Emphasis per level: the ones price is expected to deal from stand out. */
function levelStyle(l: GoldbachLevel): { color: string; width: number; dash?: number[] } {
  if (l.role === 'Ext') return { color: `rgba(${C.ext},0.55)`, width: 1, dash: [5, 4] }
  if (l.role === 'EQ') return { color: `rgba(${C.eq},0.8)`, width: 1.2, dash: [2, 3] }
  if (l.role === 'High' || l.role === 'Low') return { color: `rgba(${C.strong},0.9)`, width: 1.4 }
  if (ENTRY_ROLES.includes(l.role)) return { color: `rgba(${C.level},0.7)`, width: 1 }
  return { color: `rgba(${C.level},0.4)`, width: 1 }
}

/** Levels of the higher range worth naming — the rest would just be noise. */
const HIGHER_LABELLED = ['High', 'Low', 'EQ', 'Ext', 'OB', 'FV']

function levelShapes(range: Po3Range, from: number, faint: boolean): IndicatorShape[] {
  return range.levels.map((l) => {
    const s = levelStyle(l)
    const named = l.role === 'Ext' || l.role === 'High' || l.role === 'Low' || l.role === 'EQ'
    const full = named ? l.label : `${l.label.split(' | ')[0]} ${l.role} | ${l.label.split(' | ')[1]}`
    const label = faint && !HIGHER_LABELLED.includes(l.role) ? undefined : full
    return {
      type: 'line',
      x1: from,
      x2: null,
      y1: l.price,
      y2: l.price,
      color: faint ? s.color.replace(/,([\d.]+)\)$/, (_m, a) => `,${(Number(a) * 0.55).toFixed(2)})`) : s.color,
      width: faint ? 1 : s.width,
      dash: s.dash,
      label,
      labelColor: faint ? `rgba(${C.level},0.45)` : s.color,
    }
  })
}

/** Premium/discount column in the right-hand gutter, banded by the partition. */
function premiumColumn(range: Po3Range, n: number): IndicatorShape[] {
  const ladder = [...range.levels]
    .filter((l) => l.role !== 'Ext')
    .sort((a, b) => a.price - b.price)
  const out: IndicatorShape[] = []
  for (let i = 1; i < ladder.length; i++) {
    const bottom = ladder[i - 1]
    const top = ladder[i]
    const mid = (bottom.ratio + top.ratio) / 2
    const premium = mid > 0.5
    // deeper into premium / discount reads stronger
    const depth = Math.abs(mid - 0.5) * 2
    out.push({
      type: 'box',
      x1: n + 1,
      x2: n + 3,
      yTop: top.price,
      yBottom: bottom.price,
      fill: `rgba(${premium ? C.premium : C.discount},${(0.18 + 0.55 * depth).toFixed(3)})`,
    })
  }
  return out
}

export function makeGoldbach(): IndicatorDef {
  return {
    id: 'goldbach',
    name: 'Goldbach PO3',
    kind: 'overlay',
    compute(candles: Candle[]): IndicatorResult {
      const n = candles.length
      if (n < 30) return { plots: [], shapes: [], legend: [{ color: `rgba(${C.level},0.8)`, value: '—' }] }
      const price = candles[n - 1].close
      const size = chooseSize(candles)
      const range = po3Range(price, size)
      const higher = po3Range(price, size * 3)
      const from = Math.max(0, n - 300)

      const shapes: IndicatorShape[] = [
        ...levelShapes(higher, from, true),
        ...levelShapes(range, from, false),
        ...premiumColumn(range, n),
      ]

      const pos = rangePosition(price, range)
      const zone = pos > 0.5 ? 'premium' : 'discount'
      const level = nearestLevel(price, range, { roles: ENTRY_ROLES })
      return {
        plots: [],
        shapes,
        legend: [
          { color: `rgba(${C.strong},1)`, value: `${size} · ${size * 3}` },
          {
            color: pos > 0.5 ? `rgba(${C.premium},1)` : `rgba(${C.discount},1)`,
            value: `${(pos * 100).toFixed(0)}% ${zone}`,
          },
          {
            color: `rgba(${C.level},0.9)`,
            value: level ? `next ${level.label.split(' | ')[0]} ${level.role}` : '—',
          },
        ],
      }
    },
  }
}

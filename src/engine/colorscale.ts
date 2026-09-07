/**
 * The two colour ramps the footprint chart is built on, kept byte-for-byte
 * identical to the ones the reference orderflow chart uses:
 *
 *   icefire_r  imbalance heat — buyers burn red/orange, sellers cool to blue,
 *              balanced rows sit on the pale cream mid-point
 *   RdYlGn     the parameters strip under the chart
 */

type Stop = [number, [number, number, number]]

function stops(hex: string[]): Stop[] {
  return hex.map((h, i) => {
    const n = parseInt(h.slice(1), 16)
    return [i / (hex.length - 1), [(n >> 16) & 255, (n >> 8) & 255, n & 255]] as Stop
  })
}

const ICEFIRE_R = stops([
  '#000000', '#4c0000', '#820000', '#ac2301', '#c65400', '#da8200', '#e7b000',
  '#f3d573', '#e1e9d1', '#9be4ef', '#54c8df', '#30a4ca', '#217eb8', '#0e58a8',
  '#003786', '#001f4d', '#000000',
])

const RD_YL_GN = stops([
  '#a50026', '#d73027', '#f46d43', '#fdae61', '#fee08b', '#ffffbf',
  '#d9ef8b', '#a6d96a', '#66bd63', '#1a9850', '#006837',
])

function sample(scale: Stop[], t: number): [number, number, number] {
  const x = Math.max(0, Math.min(1, t))
  let i = 1
  while (i < scale.length - 1 && scale[i][0] < x) i++
  const [t0, a] = scale[i - 1]
  const [t1, b] = scale[i]
  const f = t1 === t0 ? 0 : (x - t0) / (t1 - t0)
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
  ]
}

function css(rgb: [number, number, number], alpha?: number): string {
  return alpha === undefined
    ? `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`
    : `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`
}

/**
 * Both ends of icefire run to black, which reads as "no data" rather than
 * "extreme". Rows with one empty side sit exactly at ±1, so pull the ends in
 * a little and keep the sign legible.
 */
const IMB_CLAMP = 0.9

/** Imbalance in [-1, 1] to a cell colour. */
export function imbalanceColor(z: number, alpha?: number): string {
  return css(sample(ICEFIRE_R, (clampImb(z) + 1) / 2), alpha)
}

function clampImb(z: number): number {
  return Math.max(-IMB_CLAMP, Math.min(IMB_CLAMP, z))
}

/** Signed parameter value to a red→green cell colour (tanh-squashed, as in the reference). */
export function paramColor(value: number, alpha?: number): string {
  return css(sample(RD_YL_GN, (Math.tanh(value) + 1) / 2), alpha)
}

/** Ink that stays readable on a given cell colour. */
export function inkFor(z: number): string {
  const [r, g, b] = sample(ICEFIRE_R, (clampImb(z) + 1) / 2)
  return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? '#0b0f16' : '#e8edf7'
}

export function paramInk(value: number): string {
  const [r, g, b] = sample(RD_YL_GN, (Math.tanh(value) + 1) / 2)
  return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? '#12161d' : '#f2f5fa'
}

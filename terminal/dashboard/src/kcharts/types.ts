// Copied from the KCharts app in this repository (src/data/types.ts) — the user's own canvas chart
// engine, reused for the K Terminal dashboard. Changes for K Terminal are marked
// "K Terminal:"; keep the rest in step with the original.

export interface Candle {
  time: number // bucket open time, ms epoch
  open: number
  high: number
  low: number
  close: number
  volume: number
}

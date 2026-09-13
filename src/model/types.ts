import type { Candle } from '../data/types'

export type Side = 'bull' | 'bear'

/** One limb of the ensemble: an independent model that votes on direction. */
export interface LimbVote {
  /** limb id, e.g. 'structure' */
  id: string
  /** short display name */
  name: string
  /** -1 (max bearish) … +1 (max bullish); 0 = no opinion */
  vote: number
  /** weight this limb carries in the blend */
  weight: number
  /** one-line human reason for the current vote */
  note: string
}

/** The ensemble's read of a single bar. */
export interface ModelBar {
  /** weighted blend of every limb vote, -1 … +1 */
  score: number
  /** score after the volatility/liquidity regime gate (this is what trades) */
  gated: number
  /** 0 … 1 — how tradeable the regime is */
  gate: number
  /** per-limb breakdown, only materialised for the inspected bar */
  votes: LimbVote[] | null
}

export type ZoneKind = 'ob' | 'fvg'

/** A supply/demand area derived from structure. Causal: only visible from `known`. */
export interface Zone {
  kind: ZoneKind
  side: Side
  top: number
  bottom: number
  /** bar the zone is drawn from */
  from: number
  /** first bar at which the model is allowed to see it */
  known: number
  /** bar it was mitigated/filled, or null while still live */
  until: number | null
}

export interface StructureEvent {
  bar: number
  side: Side
  type: 'BOS' | 'CHoCH'
  level: number
}

export interface Swing {
  idx: number
  price: number
  kind: 'H' | 'L'
  /** bar index at which the swing is confirmed (idx + strength) */
  confirm: number
}

/** An impulse leg between two confirmed swings — the anchor for fib work. */
export interface Leg {
  from: number
  to: number
  fromPrice: number
  toPrice: number
  side: Side
  /** bar from which the leg is known (confirm bar of its end swing) */
  known: number
}

export type ExitReason = 'target' | 'stop' | 'trail' | 'flip' | 'open'

export interface Fill {
  bar: number
  time: number
  price: number
  qty: number
  /** 'buy' adds to a long / covers a short */
  action: 'buy' | 'sell'
  label: string
}

export interface Position {
  id: string
  symbol: string
  side: Side
  /** bar the position was opened on */
  bar: number
  /** the Goldbach level the entry rested on, when it was a limit fill */
  level?: string
  time: number
  entry: number
  stop: number
  initialStop: number
  targets: number[]
  /** contracts/units still open */
  qty: number
  initialQty: number
  /** risk per unit at entry, in price */
  risk: number
  /** conviction (|gated score|) that opened it */
  conviction: number
  fills: Fill[]
  realized: number
  /** highest (long) / lowest (short) close seen while open */
  extreme: number
  /** limb votes at entry — the "why" behind the trade */
  votes: LimbVote[]
  /** bookkeeping: PnL already moved into cash */
  banked?: number
  /** bookkeeping: how the most recent exit fill came about */
  lastReason?: ExitReason
}

/** A limit order resting at a Goldbach level, waiting for price to come to it. */
export interface PendingOrder {
  side: Side
  /** limit price — a Goldbach level */
  price: number
  /** the level it is resting on, e.g. "0.83 FV | 81" */
  level: string
  qty: number
  stop: number
  conviction: number
  /** bar the order was placed on */
  bar: number
  /** bar index after which the order is pulled */
  expires: number
  votes: LimbVote[]
}

export interface ClosedTrade extends Position {
  exitBar: number
  exitTime: number
  exitPrice: number
  reason: ExitReason
  /** net profit in quote currency */
  pnl: number
  /** profit in R multiples */
  r: number
}

export interface EquityPoint {
  bar: number
  time: number
  equity: number
}

export interface RunStats {
  trades: number
  wins: number
  losses: number
  winRate: number
  expectancyR: number
  profitFactor: number
  totalR: number
  pnl: number
  maxDrawdown: number
  returnPct: number
}

export interface ModelRun {
  candles: Candle[]
  bars: ModelBar[]
  zones: Zone[]
  events: StructureEvent[]
  legs: Leg[]
  open: Position | null
  /** limit order currently resting, if any */
  pending: PendingOrder | null
  closed: ClosedTrade[]
  equity: EquityPoint[]
  stats: RunStats
  /** limb breakdown on the most recent bar */
  votes: LimbVote[]
  /** PO3 dealing-range size the model framed this instrument with */
  po3: number
  startEquity: number
}

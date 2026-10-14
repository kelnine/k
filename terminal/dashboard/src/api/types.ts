// Response shapes of the K Terminal API (terminal/backend/src/kterminal/api/schemas.py).
// Money, prices and quantities arrive as decimal strings and are only turned into
// numbers for display (src/lib/format.ts); timestamps are UTC ISO-8601 strings.

export type Decimal = string
export type Iso = string
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json }

export type Role = 'VIEWER' | 'OPERATOR' | 'ADMIN'

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface User {
  id: string
  username: string
  role: Role
}

export interface Session {
  user: User
  csrf_token: string
  expires_at: Iso
}

export interface FeedStatus {
  provider: string | null
  last_bar_open: Iso | null
  lag_seconds: number | null
  state: string | null
  last_error: string | null
}

export interface InstanceRuntime {
  state: string | null
  fault: Json
  account_id: string | null
}

export interface RuntimeStatus {
  session_id: string | null
  run_id: string | null
  status: string | null
  started_at: Iso | null
  updated_at: Iso | null
  last_batch_close: Iso | null
  instruments: Record<string, FeedStatus>
  instances: Record<string, InstanceRuntime>
  kill_switch: { global: boolean | null; accounts: Json; strategies: Json } | null
}

export interface RuntimeView {
  present: boolean
  stale: boolean
  age_seconds: number | null
  stale_after_seconds: number
  status: RuntimeStatus | null
  error: string | null
}

export interface Version {
  id: string
  config_hash: string
  definition_version: string
  code_hash: string | null
  params: Record<string, Json>
  timeframe: string | null
  context_timeframes: string[]
  instruments: string[]
  created_at: Iso
}

export interface Instance {
  id: string
  name: string
  description: string
  definition_id: string
  definition_name: string
  kind: string
  status: string
  enabled: boolean
  tags: string[]
  version: Version | null
  versions: number
  account_id: string | null
  runtime: InstanceRuntime | null
}

export interface InstanceDetail extends Instance {
  version_history: Version[]
}

export interface Metrics {
  starting_balance: Decimal
  balance: Decimal
  equity: Decimal
  equity_at: Iso | null
  open_pnl: Decimal | null
  net_pnl: Decimal
  return_pct: Decimal
  trades: number
  wins: number
  losses: number
  scratches: number
  win_rate: Decimal | null
  gross_profit: Decimal
  gross_loss: Decimal
  profit_factor: Decimal | null
  average_r: Decimal | null
  realized_r: Decimal
  avg_winner: Decimal | null
  avg_loser: Decimal | null
  expectancy: Decimal | null
  max_drawdown: Decimal | null
  max_drawdown_pct: Decimal | null
  open_positions: number
  low_sample: boolean
  last_trade_at: Iso | null
}

export interface Account {
  id: string
  name: string
  kind: 'FORWARD' | 'RUN'
  mode: string
  broker: string
  status: string
  currency: string
  instance_id: string | null
  instance_name: string | null
  definition_id: string | null
  definition_name: string | null
  run_id: string | null
  run_kind: string | null
  run_name: string | null
  version: Version | null
  metrics: Metrics
  halted: boolean
  runtime: InstanceRuntime | null
  created_at: Iso
}

export interface AccountDetail extends Account {
  config_version: number | null
  config: Record<string, Json> | null
  high_water_mark: Decimal
  kill_switches: KillSwitch[]
}

export interface EquityPoint {
  ts: Iso
  balance: Decimal
  equity: Decimal
  open_pnl: Decimal
  drawdown: Decimal
}

export interface Equity {
  account_id: string
  starting_balance: Decimal
  points: EquityPoint[]
  total_points: number
  downsampled: boolean
}

export interface Trade {
  id: string
  account_id: string
  account_name: string
  instance_id: string
  strategy_version_id: string
  run_id: string | null
  mode: string
  instrument: string
  venue: string
  venue_symbol: string
  timeframe: string
  direction: 'LONG' | 'SHORT'
  status: 'OPEN' | 'CLOSED'
  qty: Decimal
  entry_requested: Decimal
  entry_price: Decimal
  entry_time: Iso
  initial_stop: Decimal
  initial_target: Decimal | null
  current_stop: Decimal | null
  current_target: Decimal | null
  exit_price: Decimal | null
  exit_time: Iso | null
  exit_reason: string | null
  initial_risk: Decimal
  gross_pnl: Decimal | null
  commission: Decimal
  swap: Decimal
  funding: Decimal
  spread_cost: Decimal
  net_pnl: Decimal | null
  r_multiple: Decimal | null
  entry_slippage: Decimal | null
  exit_slippage: Decimal | null
  mae: Decimal | null
  mfe: Decimal | null
  session: string | null
}

export interface Position extends Trade {
  last_price: Decimal | null
  last_price_at: Iso | null
  unrealized_pnl: Decimal | null
  unrealized_r: Decimal | null
}

export interface Signal {
  id: string
  instance_id: string
  strategy_version_id: string | null
  source: string
  run_id: string | null
  instrument: string | null
  timeframe: string | null
  bar_time: Iso | null
  signal_time: Iso
  received_at: Iso
  action: string | null
  order_type: string
  entry: Decimal | null
  stop_loss: Decimal | null
  take_profit: Decimal | null
  risk_pct: Decimal | null
  confidence: Decimal | null
  reason: string | null
  status: string
  reject_code: string | null
  reject_detail: string | null
  metadata: Record<string, Json>
}

export type Outcome = 'APPROVED' | 'REJECTED' | 'INVALID' | 'IGNORED' | 'NO_DECISION'

export interface DecisionSummary {
  id: string
  account_id: string
  decided_at: Iso
  approved: boolean
  primary_reason: string | null
  approved_qty: Decimal | null
  risk_amount: Decimal | null
}

export interface SignalLogItem extends Signal {
  decision: DecisionSummary | null
  outcome: Outcome
  outcome_code: string | null
}

export interface Decision extends DecisionSummary {
  requested_qty: Decimal | null
  risk_pct: Decimal | null
  rule_results: Json[]
  account_state: Record<string, Json>
  quote: Record<string, Json>
}

export interface Order {
  id: string
  purpose: string
  side: string
  order_type: string
  qty: Decimal
  requested_price: Decimal | null
  status: string
  filled_qty: Decimal
  avg_fill_price: Decimal | null
  slippage: Decimal | null
  commission: Decimal
  reject_reason: string | null
  created_at: Iso
  submitted_at: Iso | null
  completed_at: Iso | null
}

export interface Fill {
  id: string
  order_id: string
  ts: Iso
  qty: Decimal
  price: Decimal
  commission: Decimal
  liquidity: string | null
  spread_cost: Decimal
  slippage: Decimal
}

export interface TradeEvent {
  id: string
  ts: Iso
  kind: string
  old_value: Decimal | null
  new_value: Decimal | null
  signal_id: string | null
  details: Record<string, Json>
}

export interface LedgerEntry {
  ts: Iso
  kind: string
  amount: Decimal
  balance_after: Decimal
  note: string
}

export interface TradeExplain {
  trade: Trade
  definition_id: string
  definition_name: string
  version: Version
  account_config: { id: string; version: number; config: Record<string, Json> }
  catalog_fingerprint: string | null
  entry_signal: Signal
  entry_market_snapshot: Record<string, Json>
  exit_signal: Signal | null
  decision: Decision | null
  orders: Order[]
  fills: Fill[]
  events: TradeEvent[]
  ledger: LedgerEntry[]
}

export interface Candle {
  t: Iso
  o: Decimal
  h: Decimal
  l: Decimal
  c: Decimal
  v: Decimal | null
}

export interface TradeMarker {
  trade_id: string
  account_id: string
  instance_id: string
  timeframe: string
  direction: 'LONG' | 'SHORT'
  status: 'OPEN' | 'CLOSED'
  qty: Decimal
  entry_time: Iso
  entry_price: Decimal
  exit_time: Iso | null
  exit_price: Decimal | null
  exit_reason: string | null
  initial_stop: Decimal
  initial_target: Decimal | null
  current_stop: Decimal | null
  current_target: Decimal | null
  net_pnl: Decimal | null
  r_multiple: Decimal | null
}

export interface Candles {
  instrument: string
  timeframe: string
  source: string | null
  sources: string[]
  built_from: string | null
  candles: Candle[]
  markers: TradeMarker[]
}

export interface InstrumentSummary {
  symbol: string
  name: string | null
  asset_class: string | null
  instances: string[]
  timeframes: string[]
  open_positions: number
  feed: FeedStatus | null
  last_candle_at: Iso | null
}

export interface InstrumentDetail extends InstrumentSummary {
  accounts: Account[]
  positions: Position[]
}

export interface Run {
  id: string
  kind: string
  name: string
  status: string
  created_at: Iso
  started_at: Iso | null
  finished_at: Iso | null
  summary: Record<string, Json> | null
  error: string | null
  instances: string[]
  accounts: number
  signals: number
  trades: number
}

export type KillSwitchScope = 'GLOBAL' | 'ACCOUNT' | 'STRATEGY'

export interface KillSwitch {
  scope: KillSwitchScope
  scope_id: string
  label: string
  active: boolean
  close_positions: boolean
  cancel_orders: boolean
  reason: string
  changed_by: string
  changed_by_username: string | null
  changed_at: Iso
}

export interface KillSwitchEvent {
  seq: number
  ts: Iso
  actor: string
  action: string
  scope: string
  scope_id: string
  data: Record<string, Json>
}

export interface KillSwitches {
  switches: KillSwitch[]
  history: KillSwitchEvent[]
}

export interface Fault {
  id: string
  ts: Iso
  component: string
  severity: string
  message: string
  strategy_instance_id: string | null
  run_id: string | null
  context: Record<string, Json>
}

export interface Overview {
  server_time: Iso
  environment: string
  live_trading_permitted: boolean
  runtime: RuntimeView
  global_halt: boolean
  active_kill_switches: KillSwitch[]
  forward: {
    accounts: number
    instances_enabled: number
    open_positions: number
    closed_trades: number
    net_pnl: Decimal
    equity: Decimal
    starting_balance: Decimal
  }
  recent_runs: Run[]
  faults_24h: number
}

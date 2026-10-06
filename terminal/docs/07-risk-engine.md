# 7. Risk-Engine Design

## 7.1 Position in the system

```
Signal ─► SignalRouter ─► (per account, serialized) ─► RiskEngine.evaluate() ─► RiskDecision
                                                              │ approved
                                                              ▼
                                                        ApprovedOrder ─► ExecutionEngine ─► BrokerAdapter
```

* **Every risk-increasing order passes through the risk engine.** The
  execution engine's `submit()` accepts only an `ApprovedOrder`, which only
  the risk engine constructs. The execution engine re-verifies that the
  referenced `risk_decision` exists, is approved, has not expired (default
  TTL 5 s for market orders) and that the order parameters hash matches the
  approved ones. The `orders` table additionally has a `CHECK` that every
  `ENTRY` order references a risk decision.
* **Risk-reducing actions are always allowed**: exits, flattening, cancelling
  orders, and stop moves *toward* or *through* entry are never blocked — not
  by the kill switch, not by a breached account. Blocking an exit is how
  accounts blow up.
* **Pure and deterministic**: `evaluate()` takes plain data and returns a
  decision; it performs no I/O. The orchestrator gathers inputs, persists the
  decision and acts on it. The same code runs in backtests.
* **Serialized per account**: decisions for one account are taken under a
  per-account lock, so two simultaneous signals cannot both pass a
  "max 1 open position" check.

## 7.2 Inputs and outputs

```python
def evaluate(
    intent: OrderIntent,        # from the Signal: strategy, symbol, direction, entry, SL, TP, requested risk %
    account: AccountState,      # balance, equity, open P&L, day-start balance/equity, high-water mark,
                                # open positions (with stops), pending orders, trades today, status
    profile: RiskProfileConfig, # the account's rules (7.4)
    instrument: InstrumentSpec, # tick size, contract size, min qty, qty step, sessions
    quote: Quote,               # bid/ask/time/provider — must be fresh
    switches: KillSwitchState,  # global / account / strategy
    now: datetime,              # from the injected Clock
) -> RiskDecision
```

`RiskDecision` contains `approved`, `approved_qty`, `risk_amount`,
`risk_pct`, the **result of every rule** (`rule`, `passed`, `code`,
`message`, the numbers it compared), `primary_reason` (first failing rule),
plus snapshots of `account` and `profile`. All rules are evaluated even after
one fails, so the record shows the complete picture.

## 7.3 Rule pipeline (evaluation order)

| # | Rule | Rejects when | Reason code |
|---|---|---|---|
| 1 | `KillSwitchRule` | Global, account or strategy kill switch active | `KILL_SWITCH_ACTIVE` |
| 2 | `ModeRule` | Account `LIVE` without every live interlock (see 09) | `LIVE_NOT_PERMITTED` |
| 3 | `AccountStatusRule` | Account `BREACHED`, `LOCKED_FOR_DAY`, `PASSED` (if `stop_on_target`), `PAUSED` | `ACCOUNT_<STATUS>` |
| 4 | `MarketDataRule` | Quote older than `max_quote_age` (default 5 s live) or spread > `max_spread_ticks` | `STALE_QUOTE` / `SPREAD_TOO_WIDE` |
| 5 | `SymbolRule` | Symbol not in `allowed_symbols` | `SYMBOL_NOT_ALLOWED` |
| 6 | `SessionRule` | Outside `trading_sessions`, inside a blackout window, or within `flat_before_close` of session end | `OUTSIDE_SESSION` |
| 7 | `StopLossRule` | No SL, SL on the wrong side, SL distance < `min_stop_ticks` or > `max_stop_pct` | `STOP_REQUIRED` / `STOP_TOO_TIGHT` / `STOP_TOO_WIDE` |
| 8 | `RewardRiskRule` | TP present and R:R < `min_rr`, or TP required but missing | `RR_BELOW_MIN` |
| 9 | `ExistingPositionRule` | Same-direction position exists and pyramiding not allowed; opposite position and hedging not allowed (reverse = exit, then re-evaluate) | `POSITION_EXISTS` / `HEDGING_NOT_ALLOWED` |
| 10 | `MaxOpenPositionsRule` | Open positions (+ pending entries) ≥ `max_open_positions` (account-wide and per symbol) | `MAX_POSITIONS` |
| 11 | `MaxTradesPerDayRule` | Entries today ≥ `max_trades_per_day` | `MAX_TRADES_TODAY` |
| 12 | `PositionSizeRule` | Computed qty < `min_qty` after rounding, or > `max_qty`, or margin insufficient | `SIZE_TOO_SMALL` / `SIZE_TOO_LARGE` / `INSUFFICIENT_MARGIN` |
| 13 | `RiskPerTradeRule` | Actual risk % after rounding > `max_risk_pct` | `RISK_TOO_HIGH` |
| 14 | `DailyLossRule` | Worst-case daily P&L (7.6) would breach the daily limit minus buffer | `DAILY_LOSS_LIMIT` |
| 15 | `MaxDrawdownRule` | Worst-case equity would breach the static/trailing drawdown floor minus buffer | `MAX_DRAWDOWN` |
| 16 | `ProfitTargetRule` | Target reached and `stop_on_target` is set | `PROFIT_TARGET_REACHED` |

Rules are plug-ins (`@register_risk_rule`) — e.g. a news blackout or a
correlation-exposure rule is added without touching the engine. A rule that
raises an exception counts as a rejection (`RULE_ERROR`), never as a pass.

## 7.4 Risk profile (per account, versioned)

```yaml
name: prop-50k-standard
default_risk_pct: 0.5            # % of equity per trade when the signal doesn't request one
max_risk_pct: 1.0                # hard cap per trade
max_daily_loss: { type: PERCENT, value: 5.0 }       # or { type: AMOUNT, value: 2500 }
daily_loss_basis: START_OF_DAY_BALANCE              # | START_OF_DAY_EQUITY | MAX_OF_BOTH
daily_loss_includes_floating: true
max_drawdown:
  type: TRAILING                 # STATIC | TRAILING
  value: { type: AMOUNT, value: 2500 }
  trailing_basis: EQUITY_INTRADAY   # | BALANCE_EOD
  lock_at_starting_balance: true    # floor stops trailing once it reaches the starting balance
safety_buffer_pct: 20            # stop at 80 % of any limit
warning_thresholds: [50, 75, 90] # % of a limit consumed → Telegram warnings
max_open_positions: 2
max_open_positions_per_symbol: 1
max_trades_per_day: 4
min_rr: 1.5
require_take_profit: false
allowed_symbols: [XAUUSD, NAS100, EURUSD]
trading_day: { timezone: America/New_York, reset_time: "17:00" }
trading_sessions:                # local times in the trading_day timezone
  - { days: [MON, TUE, WED, THU, FRI], start: "03:00", end: "16:00" }
flat_before_close_minutes: 0
profit_target: { type: PERCENT, value: 8.0 }
stop_on_target: true
allow_stop_widening: false
on_daily_limit: LOCK_FOR_DAY_AND_FLATTEN        # | LOCK_FOR_DAY
on_max_drawdown: BREACH_AND_FLATTEN
confidence_scaling: false
```

The YAML is validated by a Pydantic model; invalid profiles cannot be saved.
Every risk decision stores the profile version it used.

## 7.5 Position sizing

```
risk_pct      = min(signal.risk or profile.default_risk_pct, profile.max_risk_pct) × allocation.risk_multiplier
risk_amount   = equity × risk_pct / 100
stop_distance = |entry − stop_loss|            (entry = current ask for BUY / bid for SELL on market orders)
value_per_unit_move = contract_size × fx(quote_ccy → account_ccy)
qty_raw       = risk_amount / (stop_distance × value_per_unit_move + cost_per_unit)
qty           = floor(qty_raw / qty_step) × qty_step          ← always round DOWN
actual_risk   = qty × (stop_distance × value_per_unit_move + cost_per_unit)
```

`cost_per_unit` reserves expected commission and stop slippage so that the
realised loss of a full stop-out stays within the risk budget. Rounding down
guarantees `actual_risk ≤ risk_amount`; if the result is below `min_qty`, the
trade is rejected (`SIZE_TOO_SMALL`) rather than oversized.

Example — Paper 50K, XAUUSD, 0.5 % risk, entry 2678.40, SL 2673.20,
contract 100 oz, qty step 0.01: risk $250; stop distance 5.20 → $520 per lot;
qty = floor(0.4807 / 0.01) × 0.01 = **0.48 lots**; actual risk $249.60.

## 7.6 Daily loss and drawdown — worst-case projection

Prop firms measure losses on equity (including floating P&L), so the engine
checks the **worst case if every open stop and the new stop are hit**:

```
open_risk     = Σ open positions max(0, (current_price − stop) × qty × value/unit × side)
daily_pnl_now = equity_now − day_start_basis
worst_daily   = daily_pnl_now − open_risk − new_trade_risk
approve only if worst_daily ≥ −daily_limit × (1 − safety_buffer)

floor         = STATIC:   starting_balance − max_dd
                TRAILING: min(high_water_mark − max_dd, starting_balance if locked)
worst_equity  = equity_now − open_risk − new_trade_risk
approve only if worst_equity ≥ floor + max_dd × safety_buffer
```

Positions whose stop is at or beyond break-even contribute zero (or negative)
open risk, so locking in profit frees risk budget.

## 7.7 Continuous monitoring (between signals)

The `EquityMonitor` re-evaluates every account on each quote/bar (and at
least every few seconds live):

* Updates equity, high-water mark and drawdown; writes `equity_snapshots`.
* Emits **warnings** when 50 / 75 / 90 % of the daily-loss or drawdown limit
  is consumed (one per threshold per day → `risk_events` + Telegram).
* On a limit hit applies the profile action: `LOCK_FOR_DAY` (no new entries
  until the trading-day reset), `…_AND_FLATTEN` (close everything now),
  `BREACH` (account permanently `BREACHED`, as a prop firm would).
* Marks the account `PASSED` when the profit target is met.
* Detects stale data (no quote for N seconds while in session) → blocks new
  entries and alerts.

## 7.8 Kill switch

| Aspect | Design |
|---|---|
| Scopes | `GLOBAL`, `ACCOUNT:<id>`, `STRATEGY:<id>` |
| Effect | Blocks all new risk-increasing orders immediately (rule #1). Optionally cancels pending entry orders (`cancel_orders`, default on) and closes open positions (`close_positions`, default **off**, configurable per activation and as a global default) |
| Activation | Dashboard button, `POST /api/v1/risk/kill-switch`, Telegram `/kill`, CLI `kterminal kill`, and **automatically** on: repeated execution failures, broker disconnect with open positions, reconciliation mismatch, engine crash-loop |
| Persistence | Stored in `kill_switches`; loaded first at engine start — a restart never silently re-enables trading |
| Deactivation | Manual only (dashboard + 2FA re-auth, or CLI). Never automatic. Audited |
| Notification | `KILL SWITCH ACTIVATED` sent to every Telegram route with highest priority |

## 7.9 Testing strategy

* Unit tests per rule with explicit edge cases (exactly at the limit, one
  tick inside/outside, rounding to `min_qty`).
* **Property-based tests** (Hypothesis): for any random account state and
  signal, an approved order's worst-case loss never exceeds the remaining
  daily or drawdown budget; approved risk never exceeds `max_risk_pct`;
  risk-reducing intents are always approved.
* Scenario tests replaying prop-style days (gap through stop, trailing
  drawdown locking, daily reset across DST changes).

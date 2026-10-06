# 5. Strategy Interface Specification

Two kinds of strategy plug into the terminal, and both produce the **same
`Signal`** and go through the same risk → execution pipeline:

| Kind | Where the logic runs | How signals arrive | Backtest |
|---|---|---|---|
| `INTERNAL` | Python plug-in in `kterminal/strategies/<strategy_id>/` | `StrategyRunner` calls it on every closed bar | Full bar-by-bar backtest |
| `EXTERNAL` | TradingView (your Pine indicator/strategy) | Webhook | Signal replay of recorded/exported alerts, or port it to `INTERNAL` |

You can run a Pine strategy as `EXTERNAL` on day one, and later run its
Python port as a separate `INTERNAL` strategy (e.g. `breakout_retest` vs
`breakout_retest_tv`) side by side on identical virtual accounts. Strategy
logic is never combined unless you explicitly build a strategy that does so.

## 5.1 The standardized output: `Signal`

```python
class Signal(BaseModel, frozen=True):          # kterminal.core.models (Phase 2)
    # ── required by the brief ────────────────────────────────────────────
    strategy_id: str                # filled by the framework, never by strategy code
    symbol: str                     # canonical instrument symbol, e.g. "XAUUSD"
    timeframe: str                  # canonical: "1m" "5m" "15m" "1h" "4h" "1D" "1W"
    timestamp: datetime             # UTC open time of the bar the decision was made on
    signal: SignalAction            # LONG SHORT EXIT_LONG EXIT_SHORT MOVE_SL NO_TRADE
    entry: Decimal | None           # reference price (market) or limit/stop price
    stop_loss: Decimal | None
    take_profit: Decimal | None
    risk: Decimal | None            # REQUESTED risk, % of equity (0.5 = 0.5 %); capped by the risk profile
    confidence: float | None        # 0.0 – 1.0, optional
    metadata: dict[str, JsonValue]  # free-form, stored verbatim (levels, indicator values, reasons)
    # ── optional extensions ──────────────────────────────────────────────
    order_type: OrderType = MARKET  # MARKET | LIMIT | STOP
    expires_after_bars: int | None  # pending LIMIT/STOP entries are cancelled after N bars
    reason: str | None              # human-readable; required for a persisted NO_TRADE
    persist: bool = False           # persist a NO_TRADE (otherwise only counted)
```

### Validation rules (enforced by the framework before anything else sees the signal)

| `signal` | `entry` | `stop_loss` | `take_profit` | Rules |
|---|---|---|---|---|
| `LONG` | required | **required** | optional | `stop_loss < entry`; `take_profit > entry` if set |
| `SHORT` | required | **required** | optional | `stop_loss > entry`; `take_profit < entry` if set |
| `EXIT_LONG` / `EXIT_SHORT` | optional (reference) | — | — | Closes this strategy's position on `symbol` |
| `MOVE_SL` | — | **required** (new stop) | optional (new target) | Must not widen risk unless the risk profile allows it |
| `NO_TRADE` | — | — | — | `reason` recommended |

Every entry must carry a stop-loss: position size is derived from the stop
distance, so "no stop" means "no trade". Prices are rounded to the
instrument's tick size; `risk` must be `> 0` and `confidence` within `[0, 1]`.

### Semantics of `risk` and `confidence`

* `risk` is a **request**. Final risk % =
  `min(signal.risk or profile.default_risk_pct, profile.max_risk_pct) × allocation.risk_multiplier`.
  Sizing itself is done by the risk engine per account, never by the strategy.
* `confidence` is recorded for analytics (does confidence ≥ 0.7 really
  perform better?). Scaling risk by confidence is a risk-profile option,
  **off** by default.

## 5.2 The strategy SDK

```python
# kterminal/strategy_engine/base.py (Phase 2)

class StrategyMeta(BaseModel, frozen=True):
    id: str                                 # ^[a-z][a-z0-9_]{2,63}$ — unique, immutable
    name: str                               # "Breakout + Retest"
    version: str                            # semver, bump on logic changes
    description: str = ""
    timeframes: tuple[str, ...]             # supported timeframes
    symbols: tuple[str, ...] | None = None  # None = any instrument
    warmup_bars: int = 200                  # history replayed before the first live bar
    on_opposite_signal: Literal["reverse", "ignore"] = "reverse"   # Pine-like default
    max_pyramiding: int = 1


class Strategy(ABC, Generic[P]):
    meta: ClassVar[StrategyMeta]
    Params: ClassVar[type[BaseModel]]       # pydantic model: defaults, bounds, docs

    def __init__(self, params: P, ctx: StrategyContext) -> None:
        self.params, self.ctx = params, ctx

    def on_start(self) -> None:
        """Called once before warm-up. Allocate indicator state here."""

    @abstractmethod
    def on_bar(self, bar: Bar) -> Signal | Sequence[Signal] | None:
        """Called once per CLOSED bar, in order. Return zero or more signals."""

    def on_position_event(self, event: PositionEvent) -> Signal | Sequence[Signal] | None:
        """Theoretical position opened/closed/stopped/target-hit. Optional."""

    def on_stop(self) -> None:
        """Called on shutdown. Optional."""
```

### `StrategyContext` — the only window a strategy has on the world (read-only)

| Member | Purpose |
|---|---|
| `ctx.symbol`, `ctx.timeframe`, `ctx.instrument` | Identity and instrument spec (tick size for rounding) |
| `ctx.bars` | `BarSeries` of closed bars, oldest → newest, numpy-backed: `.open .high .low .close .volume .time`; `ctx.bars.close[-1]` is the current bar |
| `ctx.htf("1h")` | Higher-timeframe series containing **completed** HTF bars only (no look-ahead) |
| `ctx.position` | This strategy's *theoretical* position on the symbol (see 5.3) or `None` |
| `ctx.long(...)`, `ctx.short(...)`, `ctx.exit_long()`, `ctx.exit_short()`, `ctx.move_sl(...)`, `ctx.no_trade(reason)` | Signal builders that fill `strategy_id`, `symbol`, `timeframe`, `timestamp` |
| `ctx.log` | Logger bound with strategy/symbol/timeframe |
| `ctx.rng` | Seeded random generator (deterministic) |

### Rules every strategy must follow

1. **Deterministic and pure**: no network, files, database, `datetime.now()`
   or unseeded randomness. Same params + same bars ⇒ same signals, in
   backtest and live.
2. **Closed bars only**: the runner delivers only completed bars, so a
   strategy cannot repaint. (Intrabar logic, if ever needed, is an explicit
   opt-in with its own backtest fill model.)
3. **No access to accounts, balances, brokers or orders** — enforced by the
   import-linter contract and by the context exposing nothing of the kind.
4. **Fail closed**: an exception in `on_bar` is caught, logged to
   `system_errors`, alerted on Telegram, and the strategy instance is marked
   `FAULTED` for that symbol (no signals) until restarted.
5. **Budget**: `on_bar` should finish in well under 50 ms; the runner records
   timings.

## 5.3 The theoretical position ("strategy book")

Each strategy instance keeps a theoretical position — the position it would
have if every one of its signals were executed, with SL/TP evaluated on bars,
exactly like Pine's strategy tester. This lets a strategy reason about "am I
in a trade?" without knowing about accounts. Accounts can diverge (the risk
engine may reject an entry on one account but not another); the router
applies `EXIT_*` and `MOVE_SL` only to account positions that actually exist
for that strategy and records "no matching position" otherwise.

* `LONG` while flat → open long. `LONG` while long → ignored unless
  `max_pyramiding > 1`. `LONG` while short → reverse (`on_opposite_signal`).
* SL/TP hits close the theoretical position and fire `on_position_event`.

## 5.4 Registration and discovery

```python
# kterminal/strategies/breakout_retest/strategy.py
from decimal import Decimal
from pydantic import BaseModel, Field
from kterminal.strategy_engine import Strategy, StrategyMeta, register_strategy
from kterminal.indicators import atr, highest

@register_strategy
class BreakoutRetest(Strategy["BreakoutRetest.Params"]):
    meta = StrategyMeta(
        id="breakout_retest", name="Breakout + Retest", version="1.0.0",
        timeframes=("5m",), symbols=("XAUUSD",), warmup_bars=100,
    )

    class Params(BaseModel):
        lookback: int = Field(20, ge=5, le=200)
        atr_len: int = Field(14, ge=2)
        rr: Decimal = Decimal("5")

    def on_bar(self, bar):
        level = highest(self.ctx.bars.high[:-1], self.params.lookback)
        ...
        return self.ctx.long(entry=bar.close, stop_loss=sl, take_profit=tp,
                             confidence=0.7, metadata={"level": level})
```

* At start-up the engine imports every sub-package of `kterminal.strategies`
  (and any installed package exposing the `kterminal.strategies`
  entry point); `@register_strategy` adds the class to the registry keyed by
  `meta.id`. Duplicate IDs are a start-up error.
* Default parameters come from `Params`; `params.yaml` in the folder can
  override them; per-allocation overrides are stored in the database.
* **Versioning:** each run records `meta.version`, a SHA-256 of the
  strategy package's source files and a hash of the effective params in
  `strategy_versions`. Changing code without bumping `version` is detected
  (hash differs) and logged as a warning; metrics can be filtered per version.

## 5.5 External (TradingView) strategies

Declared, not coded — in `config/strategies.yaml` (applied to the database):

```yaml
- id: breakout_retest_tv
  name: Breakout + Retest (TradingView)
  kind: EXTERNAL
  allowed_symbols: [XAUUSD]
  allowed_timeframes: [5m]
  defaults: { risk: 0.5 }
```

The webhook receiver maps the payload to a `Signal` (see
[06-tradingview-webhook](06-tradingview-webhook.md)); everything downstream
is identical.

## 5.6 Testing a strategy

* `kterminal.strategy_engine.testing.run_on_bars(StrategyCls, params, bars)`
  returns the signals and theoretical trades — the basis for **golden tests**
  (`tests/` inside the strategy folder) that pin behaviour.
* **Parity tests** compare a Python port with TradingView: export the Pine
  strategy's *List of Trades* (CSV) and the same chart's bars, then assert
  entry/exit times match and prices match within one tick.
* `kterminal backtest run breakout_retest --symbol XAUUSD --tf 5m --from 2024-01-01`
  runs the full pipeline (Phase 3).

## 5.7 Pine Script porting checklist

| Pine concept | Port note |
|---|---|
| `process_orders_on_close`, `calc_on_every_tick` | Default terminal behaviour = Pine default: signal on close, fill next bar open |
| `request.security(...)` | Use `ctx.htf(tf)`; never use `lookahead_on` semantics |
| `ta.rma`, `ta.ema`, `ta.atr`, `ta.rsi` | Use `kterminal.indicators` (Pine-compatible seeding), not TA-Lib |
| `na`, `nz()` | `math.nan`/`numpy.nan`; explicit `nz()` helper |
| `var` / `varip` | Instance attributes set in `on_start` |
| `strategy.exit(loss=, profit=)` in ticks | Convert with `ctx.instrument.tick_size` |
| `strategy.risk.*`, qty settings | Not ported — the risk profile owns sizing and limits |
| `pyramiding` | `meta.max_pyramiding` |
| Session / `time()` filters | Use instrument sessions with explicit time zone |
| `syminfo.mintick` rounding | `ctx.instrument.tick_size` |

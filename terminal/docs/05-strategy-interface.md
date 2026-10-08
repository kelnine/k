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

Implemented in `kterminal/domain/signals.py`.

```python
class Signal(BaseModel, frozen=True, extra="forbid"):
    # ── required by the brief ────────────────────────────────────────────
    strategy_id: str                # the strategy INSTANCE id (the unit every metric is keyed on)
    symbol: str                     # canonical instrument symbol, e.g. "XAUUSD", "MNQ", "NEARUSD"
    timeframe: str                  # canonical: "1m" "5m" "15m" "1h" "4h" "1D" (TradingView/MT5 spellings accepted)
    timestamp: datetime             # decision time, UTC = close time of the evaluated bar
    signal: SignalAction            # LONG SHORT EXIT_LONG EXIT_SHORT MOVE_SL NO_TRADE
    entry: Decimal | None           # reference price (market) or limit/stop price
    stop_loss: Decimal | None
    take_profit: Decimal | None
    risk: Decimal | None            # REQUESTED risk, % of equity (0.5 = 0.5 %); capped by the account
    confidence: float | None        # 0.0 – 1.0, optional
    metadata: dict[str, JsonValue]  # free-form, stored verbatim (≤ 16 KiB)
    # ── stamped by the framework ─────────────────────────────────────────
    strategy_version: str           # config hash of code + parameters + instruments + timeframes
    bar_time: datetime | None       # open time of the evaluated bar
    source: SignalSource            # INTERNAL | TRADINGVIEW | MANUAL | REPLAY
    # ── optional extensions ──────────────────────────────────────────────
    order_type: OrderType = MARKET  # MARKET | LIMIT | STOP
    expires_after_bars: int | None  # pending LIMIT/STOP entries are cancelled after N bars
    reason: str | None              # human-readable; recommended for NO_TRADE
    persist: bool = False           # persist a NO_TRADE (otherwise only counted)
```

Strategy code never fills in `strategy_id`, `strategy_version`, `symbol`,
`timeframe` or the timestamps: the `ctx.long/short/…` builders do, and the
runner rejects any signal whose identity — instance, version, symbol,
timeframe, source, decision time (`timestamp` = the evaluated bar's close) or
`bar_time` — does not match the instance and bar that produced it
(`IDENTITY_MISMATCH`). Every returned signal is re-validated from scratch
(`model_copy(update=…)` skips validation), so only a freshly validated copy
is ever routed; one that fails is rejected as `INVALID_SIGNAL`.

### Validation rules (enforced by the framework before anything else sees the signal)

| `signal` | `entry` | `stop_loss` | `take_profit` | Rules |
|---|---|---|---|---|
| `LONG` | required | **required** | optional | `stop_loss < entry`; `take_profit > entry` if set |
| `SHORT` | required | **required** | optional | `stop_loss > entry`; `take_profit < entry` if set |
| `EXIT_LONG` / `EXIT_SHORT` | optional (reference) | — | — | Closes this strategy's position on `symbol` |
| `MOVE_SL` | — | **required** (new stop) | optional (new target) | Must not widen risk: the book and every account refuse it (`STOP_WIDENING_NOT_ALLOWED`) |
| `NO_TRADE` | — | — | — | `reason` recommended |

Every entry must carry a stop-loss: position size is derived from the stop
distance, so "no stop" means "no trade". Prices are rounded to the
instrument's tick size; `risk` must be `> 0` and `confidence` within `[0, 1]`
(finite numbers only, at most 4 decimals); prices must be below 10¹⁴ with at
most 10 decimals (`INVALID_PRICE`); `metadata` must be plain JSON — no
NaN/Infinity, no NumPy scalars (`METADATA_NOT_JSON`) — and at most 16 KiB;
neither `metadata` nor `reason` may contain NUL characters (`NUL_CHARACTER`).
These are exactly what the database stores, so a signal is either recorded
faithfully or refused for its own instance only. A strategy may return
at most 64 objects per bar; more faults the instance as a runaway.

### Semantics of `risk` and `confidence`

* `risk` is a **request**. In the lab the account's `risk_per_trade_pct` is
  both the default and the cap — a strategy may ask for *less* risk, never
  more — so every instance in a comparison risks the same fraction of equity.
  Sizing itself is done per account by the risk layer, never by the strategy.
* `confidence` is recorded for analytics (does confidence ≥ 0.7 really
  perform better?). Scaling risk by confidence is a later risk-profile option,
  **off** by default.

## 5.2 The strategy SDK

```python
# kterminal/strategy_engine/base.py

class StrategyMeta(BaseModel, frozen=True, extra="forbid"):
    id: str                                   # ^[a-z][a-z0-9_]{2,63}$ — unique, immutable
    name: str                                 # "Breakout + Retest"
    version: str                              # semver; bump on logic changes (code is hashed anyway)
    description: str = ""
    kind: StrategyKind = INTERNAL             # EXTERNAL for TradingView definitions
    timeframes: tuple[str, ...] = ()          # supported primary timeframes; () = any
    context_timeframes: tuple[str, ...] = ()  # always-needed context, e.g. ("15m", "1h")
    instruments: tuple[str, ...] | None = None
    asset_classes: tuple[AssetClass, ...] | None = None
    sessions: tuple[str, ...] = ()            # session windows used, e.g. ("ny_orb_15",)
    warmup_bars: int = 200
    on_opposite_signal: Literal["reverse", "ignore"] = "reverse"   # Pine-like default
    max_pyramiding: int = 1
    tags: tuple[str, ...] = ()


class Strategy[P: StrategyParams](ABC):
    meta: ClassVar[StrategyMeta]
    Params: ClassVar[type[StrategyParams]] = NoParams   # frozen, extra="forbid"

    def __init__(self, params: P, ctx: StrategyContext) -> None: ...

    def on_start(self) -> None:
        """Called once before warm-up. Initialise per-instance state here."""

    @abstractmethod
    def on_bar(self, bar: Bar) -> Signal | Sequence[Signal] | None:
        """Called once per CLOSED primary-timeframe bar, in order."""

    def on_position_event(self, event: PositionEvent) -> Signal | Sequence[Signal] | None:
        """Theoretical position opened / closed / stop moved / order expired. Optional."""

    def on_stop(self) -> None:
        """Called on shutdown. Optional."""
```

### `StrategyContext` — the only window a strategy has on the world (read-only)

| Member | Purpose |
|---|---|
| `ctx.strategy_id`, `ctx.symbol`, `ctx.timeframe`, `ctx.instrument` | Identity and the canonical instrument (tick size used for rounding) |
| `ctx.bars` | `BarSeries` of closed primary-timeframe bars, oldest → newest; `.open .high .low .close .volume` are **read-only** NumPy arrays, `ctx.bars.close[-1]` is the bar being evaluated, `ctx.bars.bar(-1)` its `Bar` (Decimal prices) |
| `ctx.series("1h")` | A declared context timeframe. Higher timeframes contain only bars that have **closed** by now (no look-ahead); lower ones (e.g. `1m` precision) every bar up to the current close |
| `ctx.bar`, `ctx.now` | The bar being evaluated and its close time (strategy time) |
| `ctx.position` | This instance's *theoretical* position on the symbol (5.3) or `None` |
| `ctx.window("ny_orb_15")`, `ctx.in_window(id)` | Configured session windows (ORB ranges, London/New York sessions, kill zones) with DST-correct `window_on(date)`, `window_at(ts)`, `contains(ts)`. Only windows declared in `meta.sessions` (or used by the session classification) are available, so every window a strategy depends on is part of its version |
| `ctx.trading_day()`, `ctx.session()` | Trading day per the instrument's rollover rule (e.g. 17:00 New York) and the session label (`asia_session` / `london_session` / `ny_session`) |

Without an explicit time, `in_window`, `trading_day` and `session` look at the
evaluated bar's **open** time — a bar belongs to the window it starts in, as
with Pine's `time()` session filters. For `ny_orb_15` (09:30–09:45 New York)
the 5-minute bars opening 09:30, 09:35 and 09:40 are inside; the 09:25 bar is
not.
| `ctx.long(...)`, `ctx.short(...)`, `ctx.exit_long()`, `ctx.exit_short()`, `ctx.move_sl(...)`, `ctx.no_trade(reason)` | Signal builders: fill identity and timestamps, default `entry` to the current close, round prices to the tick |
| `ctx.log` | Logger bound with strategy/instrument/timeframe |
| `ctx.rng` | Seeded NumPy generator (deterministic per instance and instrument) |

### Rules every strategy must follow

1. **Deterministic and pure**: no network, files, database, `datetime.now()`
   or unseeded randomness. Same params + same bars ⇒ same signals, in
   backtest and live.
2. **Closed bars only**: the runner delivers only completed bars, so a
   strategy cannot repaint. (Intrabar logic, if ever needed, is an explicit
   opt-in with its own backtest fill model.)
3. **No access to accounts, balances, brokers or orders** — enforced by the
   import-linter contract and by the context exposing nothing of the kind.
4. **Fail closed**: an exception in strategy code is caught by the runner,
   recorded as a fault, and the instance stops emitting signals; every other
   instance carries on. With `host: subprocess` the instance runs in its own
   OS process, so even a hard crash or an infinite loop (per-batch time
   budget) faults only that instance.
5. **No class-level mutable state**: lists, dicts, sets or arrays assigned on
   the class would be shared between instances of the same strategy and are
   rejected at registration — also when hidden inside tuples, frozen
   dataclasses/models, nested classes, `ClassVar`s of `Params`, function
   default arguments or `functools.cache`. Initialise per-instance state in
   `on_start`. Each strategy object (one per instrument) gets its own copy of
   the parameters. Module-level globals cannot be checked: run such (or any
   untrusted) code with `host: subprocess`.
6. **Timeframes are intraday** (1m … 4h) until session-anchored daily bars
   arrive with the market-data layer; `1D`/`1W` are rejected at configuration.
7. **Budget**: `on_bar` should finish in well under 50 ms; the runner records
   timings and warns about slow bars.

## 5.3 The theoretical position ("strategy book")

Each strategy instance keeps a theoretical position — the position it would
have if every one of its signals were executed, with SL/TP evaluated on bars,
exactly like Pine's strategy tester. This lets a strategy reason about "am I
in a trade?" without knowing about accounts. Accounts can diverge (the risk
engine may reject an entry on one account but not another); the router
applies `EXIT_*` and `MOVE_SL` only to account positions that actually exist
for that strategy and records "no matching position" otherwise.

* `LONG` while flat → open long. `LONG` while long → ignored unless
  `max_pyramiding > 1`. `LONG` while short → reverse (`on_opposite_signal`):
  a MARKET reversal at the next open; a LIMIT/STOP reversal only **when it
  fills** (one order closes and re-opens, as in Pine).
* Resting entries expire after `expires_after_bars` primary bars that trade —
  counted in bars, not wall-clock time, so a weekend does not expire them.
* SL/TP hits close the theoretical position and fire `on_position_event`.
  A bar that *opens* beyond the target takes profit at the open; otherwise,
  when one bar reaches both, the stop is assumed first. On the bar a resting
  entry fills inside the bar, the target counts only if the bar closes beyond
  it (the high/low may have come before the fill). `MOVE_SL` reports
  `STOP_MOVED` / `TARGET_MOVED` on the next bar.
* The paper accounts apply exactly the same rules (plus spread, slippage and
  costs), so a strategy's `ctx.position` and its account agree unless the
  account rejected something.

## 5.4 Registration, discovery, instances and versions

```python
# kterminal/strategies/demo_sma_cross/strategy.py  (a real, runnable example)
class SmaCrossParams(StrategyParams):          # frozen + extra="forbid" (typos are errors)
    fast: int = Field(9, ge=2, le=500)
    slow: int = Field(21, ge=3, le=1_000)
    reward_risk: Decimal = Field(Decimal("2"), gt=0)

@register_strategy
class DemoSmaCross(Strategy[SmaCrossParams]):
    meta = StrategyMeta(id="demo_sma_cross", name="Demo · SMA crossover",
                        version="1.0.0", warmup_bars=50, tags=("demo",))
    Params = SmaCrossParams

    def on_bar(self, bar):
        close = self.ctx.bars.close
        ...
        return self.ctx.long(stop_loss=bar.close - stop,
                             take_profit=bar.close + stop * self.params.reward_risk)
```

* **Discovery:** every sub-package of `kterminal.strategies` is imported at
  start-up (plus installed packages exposing the `kterminal.strategies` entry
  point); `@register_strategy` validates the class and registers its
  definition. Duplicate ids are an error. `kterminal strategies list` shows
  them.
* **Instances:** `terminal/config/lab.yaml` declares instances — one
  definition can run as many instances with different parameters,
  instruments, timeframes or accounts. Each instance is its own lab subject.
* **Versions:** for every instance the framework builds a canonical document
  of the definition id and version, a **SHA-256 of the strategy's source
  folder**, the effective parameters (defaults included), instruments with
  their canonical tick sizes, timeframes, the session windows, session
  classification and trading-day rules it uses, and behaviour flags. Its hash
  (`config_hash`) is the instance's version and is stamped on every signal as
  `strategy_version`. Editing code — the strategy's folder *and* any strategy
  base class it inherits from, even without bumping `version` — parameters or
  a session/trading-day rule creates a new version. Names, descriptions, the
  host choice and how numbers are spelled (`2`, `2.0`, `"2.00"`) do not, and
  the hash is identical in every process (sets are sorted).

## 5.5 External (TradingView) strategies

Declared, not coded — in `terminal/config/lab.yaml`:

```yaml
external_strategies:
  - id: breakout_retest_tv
    name: Breakout + Retest (TradingView)
    version: 1.0.0
    timeframes: [5m]
    instruments: [XAUUSD]
    pine_source: strategies/pine/breakout_retest.pine   # optional; hashed into the version
```

An external definition gets instances, accounts and versions exactly like a
Python one. Its signals arrive through the webhook (Phase 6), are mapped to
the same `Signal`, applied to the instance's theoretical book and routed to
its own account; everything downstream is identical.

## 5.6 Testing a strategy

* `kterminal.strategy_engine.testing.run_strategy(StrategyCls, instrument=…,
  bars=…, timeframe="5m", params={…})` runs a strategy through the real runner
  (validation, theoretical book, fault handling) outside the global registry
  and returns its signals, rejected outputs, position events and any fault —
  the basis for **golden tests** (`tests/` inside the strategy folder).
* **Parity tests** compare a Python port with TradingView: export the Pine
  strategy's *List of Trades* (CSV) and the same chart's bars, then assert
  entry/exit times match and prices match within one tick (Phase 3).
* `kterminal lab demo` runs the configured instances side by side on synthetic
  data, each into its own paper account, and audits isolation from the
  recorded rows.

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
| Session / `time()` filters | Declare the window in `meta.sessions` and use `ctx.in_window(id)` — like `time()`, it tests the bar's open time, DST-correct |
| `syminfo.mintick` rounding | `ctx.instrument.tick_size` |

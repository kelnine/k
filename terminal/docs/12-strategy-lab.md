# 12. The Strategy Lab

The terminal works like a laboratory: many strategies run **side by side, on
the same market data, each on its own virtual account under identical
conditions**, and every number used to compare them is computed from the
trades they actually recorded.

## 12.1 Definitions, instances and versions

| Concept | What it is | Example | Identity |
|---|---|---|---|
| **Strategy definition** | Code (a Python plug-in) or a declared external TradingView script | `ema_cross`, `orb`, `breakout_retest_tv` | `definition_id` + semantic `version` |
| **Strategy instance** | A configured, independently measured *lab subject*: one definition + parameters + instruments + timeframes + its own paper account | `ema_cross_9_21_xau`, `ema_cross_20_50_xau`, `orb_ny_15_mnq` | `strategy_id` (instance id) |
| **Strategy version** | Immutable snapshot of everything that determines an instance's signals: definition version, **hash of the code**, effective parameters, instruments, timeframes, session settings | `0192…` (config hash `9f3c…`) | `strategy_version_id` |

* Multiple instances of the same definition with different settings are
  normal: each has its own id, account, metrics and leaderboard row.
* Every signal, risk decision and trade stores `strategy_instance_id` **and**
  `strategy_version_id`. Editing parameters or code produces a *new* version;
  rows recorded under the old version keep pointing at it, so later changes
  never corrupt historical comparisons. Metrics can be grouped per instance or
  per version.
* Accounts are versioned the same way: each risk decision and trade references
  the `account_config_version` (starting balance, risk %, limits, venue
  profile) it was made under.

### Experiments and variants (prepared now, built later)

A variant such as *A + EMA filter* or *A + B confirmation* is **its own
instance** of a composite definition — never a modification of A. It gets its
own account and metrics, so A, B and every combination remain independently
measurable. An **experiment** groups instances that are compared under one set
of conditions (same account template, venue profile and data window):

```
experiment "orb-vs-filters"
  ├─ A            orb_ny_15_mnq
  ├─ A+EMA        orb_ny_15_mnq_ema200        (composite definition: orb + ema filter)
  └─ A+B+LIQ      orb_ny_15_mnq_bos_liq
```

The database already has `experiments` and `experiment_members`; composite
definitions arrive with Experiment mode.

## 12.2 Isolation

A strategy instance cannot see, influence or break another one:

| Layer | Guarantee | How |
|---|---|---|
| Code | A strategy cannot touch accounts, orders, brokers, storage or the API | import-linter sandbox contract; the context exposes read-only data only |
| State | No shared mutable state between instances, even of the same class | one object per instance; registration rejects classes with mutable class-level attributes; parameters are frozen |
| Data | Every instance sees identical, immutable bars | frozen `Bar` objects; NumPy arrays handed to strategies are read-only |
| Failure | An exception (or, with the subprocess host, a crash or infinite loop) faults only that instance | the runner catches and records faults; `SubprocessStrategyHost` runs each instance in its own OS process with a per-bar time budget |
| Accounts | Each instance has its own paper account and ledger | dedicated accounts: `accounts.strategy_instance_id` is unique; run-scoped accounts: one `account_allocations` row to exactly one instance; signals are routed only to the instance's own account, and the account refuses signals of any other instance |
| Comparison | Results are comparable | same bars, venue profile, account template; metrics recomputed from recorded trades |

## 12.3 Accounts

Every instance trades in its own `PAPER` account (name
`Paper 50K · <instance_id>`), with a configurable starting balance that
defaults to **$50,000**. There are two kinds:

| Account | Created by | Used for | Lifetime |
|---|---|---|---|
| **Dedicated** (`accounts.strategy_instance_id` = the instance, unique) | `kterminal lab provision` (idempotent; a changed configuration becomes a new `account_config_versions` row) | forward testing on live data (Phase 3+) | persistent — one per instance, ever |
| **Run-scoped** (`… · run <id>`, linked through `account_allocations`) | every simulation (`lab demo`, backtests, replays) | that run only | one per instance per run |

Simulations never write to a dedicated account, so synthetic or historical
results can never contaminate an instance's forward-test history, and two runs
never share an account. Both kinds open with a single `DEPOSIT` ledger row;
the balance is always the sum of the ledger.

The lab configuration (`terminal/config/lab.yaml`) sets defaults for all
accounts and lets each instance override them:

```yaml
defaults:
  account:
    starting_balance: 50000
    currency: USD
    venue_profile: lab_default
    risk_per_trade_pct: 0.5
    max_open_positions: 1

instances:
  - id: demo_sma_fast
    strategy: demo_sma_cross
    params: { fast: 9, slow: 21 }
    instruments: [XAUUSD]
    timeframe: 5m
    context_timeframes: [15m, 1h]
  - id: demo_sma_slow
    strategy: demo_sma_cross
    params: { fast: 20, slow: 50 }
    instruments: [XAUUSD]
    timeframe: 5m
    account: { starting_balance: 100000 }
```

LIVE accounts cannot be created in Phase 2.

## 12.4 Multi-timeframe strategies

A strategy declares one **primary** (execution) timeframe and optional
**context** timeframes, matching a 1H context → 15m confirmation → 5m entry →
1m precision workflow. The runner calls `on_bar` once per closed primary bar;
`ctx.series("1h")` returns only higher-timeframe bars that have *closed* by
then (no look-ahead), and lower-timeframe series contain every bar up to the
current primary bar's close. Bars of all timeframes are built from one base
stream by the same aggregator for every instance.

## 12.5 Flow through the lab

```
base bars (1m) ─▶ aggregator ─▶ closed bars 1m/5m/15m/1h (identical, immutable)
                                   │ fan-out
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
   host: instance A         host: instance B          host: instance C      (in-process or subprocess)
   runner → on_bar          runner → on_bar           runner → on_bar
   theoretical book         theoretical book          theoretical book
          │ signals                │ signals                │ signals
          ▼                        ▼                        ▼
   router → account A       router → account B        router → account C    (only own allocations)
   sizing + checks          sizing + checks           sizing + checks
   paper fills + costs      paper fills + costs       paper fills + costs
          └───────────── recorder: signals, decisions, orders, fills, trades, ledger, equity ─────────────▶ PostgreSQL
```

`kterminal lab demo` runs this end to end with two dummy strategies and
prints each account's state, recomputed from the recorded trades.

## 12.6 Schema additions in Phase 2

Relative to [04-database-schema](04-database-schema.md), Phase 2 adds or
changes:

* **Reference data:** `catalog_snapshots`, `venues`, `instruments`,
  `instrument_listings`, `symbol_aliases`, `trading_calendars`,
  `trading_day_rules`, `session_windows`, `cost_profiles`, `venue_profiles`,
  `venue_profile_entries`.
* **Strategies:** `strategy_definitions`, `strategy_instances`,
  `strategy_versions` (per instance, unique config hash), `strategy_promotions`,
  `experiments`, `experiment_members`.
* **Runs:** `runs` (backtest, lab simulation, forward test, signal replay)
  replaces `backtest_runs`; signals, decisions, orders, fills, trades, ledger
  and equity rows carry an optional `run_id`.
* **Accounts:** `venue_profile_id`, dedicated `strategy_instance_id`,
  `account_config_versions`; ledger kinds include `FUNDING`.
* **Trades and fills:** instance/version/account-config references, venue and
  venue symbol, funding, spread cost and slippage columns.

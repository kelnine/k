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
| State | No shared mutable state between instances, even of the same class | one object per instance and instrument, each with its own copy of the parameters; registration rejects mutable class-level state, also hidden in tuples, frozen dataclasses, nested classes, `Params` class variables, default arguments or `functools.cache`; module globals cannot be checked statically — use `host: subprocess` for such code |
| Data | Every instance sees identical, immutable bars | frozen `Bar` objects; NumPy arrays handed to strategies are read-only; one aggregator builds every timeframe (warm-up and live alike), never emits a partial period and keeps batches in time order across data gaps |
| Arithmetic | No instance can change another's numbers | strategy code runs in its own copy of the decimal context; all money arithmetic runs in a private context |
| Output | What an instance returns cannot hurt anyone else | every signal is re-validated from scratch and must carry its own instance, version and bar time; metadata must be finite, plain JSON without NUL characters; prices and risk must fit their database columns exactly, so a signal is recorded faithfully or refused for its own instance only — it can never fail a lab write for the others; at most 64 objects per bar; rejected payloads are bounded |
| Failure | An exception — including `SystemExit` — (or, with the subprocess host, a crash or infinite loop) faults only that instance | the runner contains everything but an operator's Ctrl-C; a signal that breaks its own account faults only that instance; `SubprocessHost` runs each instance in its own OS process, and its time budget runs from dispatch, so collection order never matters; a run that fails anyway stops every host and is recorded as `FAILED` |
| Accounts | Each instance has its own paper account and ledger | dedicated accounts: `accounts.strategy_instance_id` is unique; run-scoped accounts: one `account_allocations` row to exactly one instance; signals are routed only to the instance's own account, and the account refuses signals of any other instance; the database itself refuses a trade, order or risk decision on an account not allocated to its instance, or built on another instance's signal |
| Comparison | Results are comparable | same bars, venue profile, account template; metrics recomputed from recorded trades |
| Proof | Isolation is checked, not assumed | `kterminal lab demo` audits the recorded rows (every decision and trade traces back to a signal of the account's own instance; balance = deposit + own ledger entries) **and** re-runs every instance *alone* on the same bars: its signals, trades and final balance must be identical to the run alongside the others |

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

## 12.7 Forward sessions: the lab on live data

A **forward session** runs the lab on live, closed 1-minute bars. Each
instance trades its **dedicated** account (`Paper 50K · <instance>`) — never a
run-scoped one — so forward-test history accumulates in one place per
instance. The session is a `runs` row of kind `FORWARD` that stays `RUNNING`
across restarts until it is ended (`kterminal paper end-session`, or a new
session replacing it). Everything below is paper:
fills are simulated, no broker adapter is constructed, and LIVE accounts cannot
be created.

| Step | What happens |
|---|---|
| Start | The lab is set up from `lab.yaml` and `instances.d/` (below) and the dedicated accounts are provisioned (a changed account configuration becomes a new configuration version). Each account continues from its ledger balance; a session refuses to start while one of them still has an open trade. |
| Market data | Every instrument an enabled instance trades gets its provider from the market-data layer: `load_data_sources` reads the data source map and `build_providers` builds one provider per venue ([15](15-market-data.md)). An instrument the map does not list, or whose sources are all unusable on this host (a disabled provider, OANDA without a token, `csv` without a directory), has no provider: it gets no warm-up, delivers no bars and is reported `no_provider` with the reason; its instances run but never see a bar of it. |
| Warm-up | Per instrument, the largest need of the instances trading it: `warmup_bars` of the instance's largest timeframe (+1 period, which the aggregator drops as partial), and — for a strategy whose code uses `ctx.periods` — `period_warmup_bars` of its primary timeframe for each period level it asks for ([05 §5.2.2](05-strategy-interface.md#522-previous-period-levels-pdhpdl-pwhpwl-pmhpml)). History reaches back at most `forward.warmup_days` (default 10; `kterminal paper start --warmup-days N` overrides it): stored candles of the instrument's live source first, the rest from the provider's history (stored as it arrives). A warm-up the cap or the provider cut short is logged as `paper.warmup_short`. Warm-up primes indicators; nothing trades. |
| Live loop | `forward.poll_delay_s` (default 2 s) after each minute boundary every instrument's provider is polled for bars since its newest one. The minute is processed when every instrument the session waits for has delivered it (or a later bar, which proves a gap), or `forward.batch_timeout_s` (default 20 s) after the close. It waits only for instruments whose market is open (catalog trading calendars) and whose provider is not backing off after an error (marked `stale`). A bar that arrives after its minute was processed is dropped and logged, never processed out of order. Periods of higher timeframes close when their time is over, also when their last minutes never came. |
| Commit | Each minute is one transaction: its bars into `candles`, every record the lab produced, the session's progress (`runs.data_fingerprint`) and an audit entry for each kill-switch state that took effect. |
| Restart | The open session is resumed by replaying its logged candles through a fresh lab with every write suppressed, then checked against the database before it continues live (catching up on the minutes it missed). |
| End | `kterminal paper end-session` ends the open session — its open positions are closed at their instrument's last processed price, recorded as `RUN_END` exits, and the run becomes `COMPLETED`; the next start begins a new session. `kterminal paper start --new-session` does both in one step. |

### Which instances trade

Forward sessions run every enabled instance of `config/lab.yaml` plus those in
`config/instances.d/`: every `*.yaml` / `*.yml` file there, read in file-name
order, holds a YAML list of instance entries with the same schema as
`lab.yaml`'s `instances` (each gets its account from `lab.yaml`'s `defaults`
merged with its own `account`). The directory may be missing or empty. An id
defined twice — in `lab.yaml` and a file, in two files, or twice in one file —
is an error naming both places; a file that is not a list, or an invalid entry,
is an error naming the file and the entry. Simulations (`kterminal lab demo`)
read `lab.yaml` only.

`lab.yaml`'s optional `forward` section tunes the runtime and is not part of a
session's identity:

| Key | Default | Meaning |
|---|---|---|
| `warmup_days` | 10 | How far back warm-up history may reach |
| `poll_delay_s` | 2 | First poll this long after a minute closed |
| `batch_timeout_s` | 20 | Process the minute without the instruments still missing this long after its close |

### The input log and exact replay

`candles` (keyed by instrument, timeframe, source and open time) is the
session's input log: every bar it warmed up on or processed is there, under
the source recorded in the session's input segments. The session's progress
holds a hash chain over the bars of every processed minute and the number of
lab batches.

Replay reproduces the original run exactly because nothing it depends on is
random or wall-clock based:

* **Ids** come from `SessionIds`: UUIDv7-shaped, made of the batch's close
  time, a sequence within the batch and the session's namespace (from its run
  id). They sort chronologically and are the same in a replay.
* **Bars** are processed in canonical form (`4000.0100000000` and `4000.01` are
  the same bar), so a bar read back from `candles` is the bar the live run saw.
* **Kill-switch changes** are recorded with the batch they took effect at and
  re-applied at that batch.
* **Host failures** a replay cannot cause (a subprocess time-out or crash) are
  read back from `system_errors` and re-applied at their batch; strategy
  exceptions recur by themselves.

After the replay the session compares its rebuilt state with the database: row
counts of every table it writes, every ledger entry of the session (ids,
amounts, balances), every trade (status, net P&L, exit time), each account's
ledger balance and open trades, and each account's latest equity snapshot. Any
difference, or a changed input log (warm-up or live candles), stops it with
`SessionVerificationError`.

A session is never resumed under different conditions. Resuming fails with
`SessionMismatchError`, naming each change and the command to start a new
session, when since it began:

* the lab-wide settings replay depends on changed: `base_timeframe`,
  `equity_snapshot_minutes` or the declared `external_strategies`;
* the catalog fingerprint changed;
* an enabled instance was added, removed or disabled, or has a new strategy
  version (definition code, parameters, instruments, timeframes, position
  rules);
* an instance's other lab settings changed — its merged account settings.

The `forward` section, `experiments`, disabled instances and an instance's
`host` (in-process or subprocess) can change without ending the session. The
session's recorded trades stay as they are either way.

### Kill switches

`kill_switches` holds one row per scope: `GLOBAL`, `ACCOUNT <account id>` or
`STRATEGY <instance id>`. The runtime reads the table before every minute; a
changed state takes effect in the next batch, after its fills and before its
signals:

| While a switch covers an account | |
|---|---|
| New entries | Refused: a recorded risk decision with `KILL_SWITCH_ACTIVE` (rule `kill_switch`) |
| Resting entry orders | Cancelled when the switch activates (`cancel_orders`, on by default) |
| Open positions | Kept, unless `close_positions`: then closed at the next base bar's open by `FLATTEN` orders, exit reason `KILL_SWITCH` |
| Exits, stop moves, brackets | Work as usual (a refused market reversal still closes the open position) |

Every change is written to the audit log twice: when it is made
(`killswitch.activate` / `killswitch.deactivate`, entity `kill_switch`) and
when a session applies it (`killswitch.applied`, entity `run`, with the batch
time it took effect from — what a replay re-applies).

### Runtime status (`system_state['paper.runtime']`)

Upserted after every minute and on every state change:

| Key | Meaning |
|---|---|
| `session_id` | This runtime process's attachment to the session (new on every start or restart) |
| `run_id` | The forward session (`runs.id`, kind `FORWARD`) |
| `status` | `starting`, `warming_up` (warm-up or replay), `running`, `stopped`, `error` |
| `started_at` | The session's first live minute |
| `updated_at` | When this document was written |
| `last_batch_close` | Close time of the newest processed minute (`null` before the first) |
| `instruments.<SYMBOL>` | `provider` (its name, `null` without one), `last_bar_open` (newest processed bar), `lag_seconds` (now − that bar's close), `state` (`ok`, `stale`, `closed`, `no_provider`), `last_error` (the provider's last error; for `no_provider` why there is none) |
| `instances.<ID>` | `state` (strategy host: `RUNNING`, `FAULTED`, `STOPPED`), `fault`, `account_id` |
| `kill_switch` | `global` (bool), `accounts` and `strategies` with an active switch |
| `error` | The reason, when `status` is `error` |

When the engine cannot even build the runtime (an invalid data source map, say)
it publishes `status: error` with the reason and `null` / empty values for the
rest — unless another runtime holds the lock, whose status then stands.

Operating it — starting, restarting, replacing a session, using the kill
switch — is described in [16-running-paper-trading](16-running-paper-trading.md).

# 16. Running paper trading

The forward paper runtime trades every enabled instance in `config/lab.yaml`
and `config/instances.d/` on live, closed 1-minute bars, each in its own dedicated `Paper 50K` account,
and records everything in PostgreSQL every minute. How it works is described
in [12.7](12-strategy-lab.md#127-forward-sessions-the-lab-on-live-data); this
document is the operator's side. Nothing here can place a real order: fills
are simulated, no broker adapter is constructed, and LIVE accounts cannot be
created.

## 16.1 Before the first start

| Step | Command / file |
|---|---|
| Schema up to date | `kterminal db upgrade` (Docker: the `migrate` service does it) |
| Instances to trade | `config/lab.yaml` and the files in `config/instances.d/` ([12.7](12-strategy-lab.md#which-instances-trade)); `kterminal strategies list` shows lab.yaml's |
| Market data | `kterminal data sources` shows each instrument's provider and whether it is usable on this host ([15](15-market-data.md)). An instrument without a usable provider (no OANDA token, a disabled venue, not in the data source map) is reported `no_provider` with the reason and never trades |
| History (optional) | `kterminal data import-csv FILE --instrument XAUUSD --source <provider>` loads bars (a generic OHLCV file or a TradingView export) into `candles`. Warm-up uses stored candles of the instrument's live source, so import under the provider's name (`oanda`, `binance_usdm` …) to save downloads. `kterminal data candles` lists what is stored |
| Tuning (optional) | `forward:` in `lab.yaml` — `warmup_days` (10), `poll_delay_s` (2), `batch_timeout_s` (20) |

`kterminal lab provision` is optional: it creates the dedicated accounts of
`lab.yaml`'s instances ahead of time (to see their ids); starting a session
provisions every forward instance's account itself, `instances.d/` included.

## 16.2 Running it locally without Docker

For a first test on one machine: PostgreSQL 16 (`make dev-db` starts one in
Docker on 127.0.0.1:5432, or use your own), Python 3.12 and `uv`. From the
`terminal/` directory:

```bash
cp .env.example .env                 # then edit; every setting is KT_<GROUP>__<NAME>
uv sync --project backend
uv run --project backend kterminal db upgrade        # schema
uv run --project backend kterminal catalog validate  # optional: the catalog loads
uv run --project backend kterminal data sources      # which instruments have market data
uv run --project backend kterminal lab provision     # optional: accounts ahead of time
uv run --project backend kterminal paper start       # Ctrl-C stops it; start again resumes
```

In a second terminal: `uv run --project backend kterminal paper status`.

| Variable | Needed | Value |
|---|---|---|
| `KT_DATABASE__URL` | yes | e.g. `postgresql+asyncpg://kterminal@localhost:5432/kterminal` (`postgresql://` is accepted too) |
| `KT_DATABASE__PASSWORD` | if not in the URL | the database password |
| `KT_PATHS__CONFIG_DIR` | when not run from `terminal/` | the `config` directory (catalog, `lab.yaml`, `instances.d/`) |
| `KT_MARKETDATA__OANDA_TOKEN` | for FX, metals and index CFDs | an OANDA v20 API token (read-only use: candles); without it those instruments are `no_provider` |
| `KT_MARKETDATA__OANDA_ENVIRONMENT` | if the token is for a live OANDA account | `live` (default `practice`); selects where prices are read, not LIVE trading |
| `KT_MARKETDATA__DISABLED_PROVIDERS` | where a venue is blocked | e.g. `binance_usdm,binance_spot,bybit_linear` — instruments fall back to their alternative sources |
| `KT_MARKETDATA__CSV_DIR` | for the `csv` provider (MNQ) | directory of imported `<INSTRUMENT>.csv` files |
| `KT_LOGGING__FORMAT` | no | `console` for readable logs (default `json`) |

The rest of the market-data settings are in [15](15-market-data.md). The
crypto venues need no key. `kterminal paper start` refuses to start (exit code
2) when the data source map or the market-data settings are invalid, and
prints which instruments have no market data before it starts.

## 16.3 Starting

| Where | How |
|---|---|
| Docker | The `engine` service runs the paper runtime as soon as it is the leader — nothing else to do. Without `config/lab.yaml` it runs without it. It reads the configuration, the catalog and the data source map afresh on every (re)start of the runtime |
| Foreground | `kterminal paper start [--warmup-days N]` — runs until Ctrl-C / SIGTERM |

Only one runtime may run against a database (an advisory lock): with the
engine running, `paper start` stops with *another paper runtime is already
running*. Stop the engine first, or let the engine do the work.

The first start creates the session: accounts are provisioned, each instrument
is warmed up on recent history (enough for every instance trading it; at most
`forward.warmup_days`, default 10, or `--warmup-days`) and live trading starts
at the current minute. Logs show `paper.warmup` per instrument (and
`paper.warmup_short` when the cap or the provider's history cut it short) and
`paper.session_started`. An instrument that had no provider when the session
started gets no warm-up in that session: after configuring its provider,
start a new session (16.6) so its instances are primed.

## 16.4 Watching it

* `kterminal paper status` — the runtime's last published status (instruments
  with provider, state and lag; instances with their host state and faults;
  kill switches) and the open session's accounts with balances and trade
  counts.
* `kterminal paper sessions` — every forward session, newest first.
* The dashboard reads the same document from `system_state['paper.runtime']`
  (schema in [12.7](12-strategy-lab.md#runtime-status-system_statepaperruntime)).

| Instrument state | Meaning |
|---|---|
| `ok` | Delivering bars |
| `closed` | Market closed (catalog calendar) — not waited for |
| `stale` | The provider failed (retried with back-off: 5 s, doubling up to 5 min) or the last minute arrived too late; it recovers by itself |
| `no_provider` | It has no usable provider; `last_error` says why (not in the data source map, no OANDA token, provider disabled) |

Logged events worth alerting on: `paper.feed.provider_error`,
`paper.feed.minute_missing`, `paper.feed.late_bar_dropped` (a bar that came
after its minute was processed — dropped, never processed out of order),
`paper.commit_failed`, `paper.runtime_failed`, `paper.warmup_short`,
`engine.paper_runtime_stopped` (the engine retries the runtime a minute later).

## 16.5 Stopping and restarting

Ctrl-C or SIGTERM (`docker compose stop engine`) finishes the minute in
progress and stops. The session stays open: its positions remain open on
paper and nothing is processed while it is stopped.

On the next start the runtime **resumes** the session: it replays the
session's logged candles through a fresh lab without writing anything, checks
the rebuilt state against the database (status `warming_up` meanwhile), then
catches up on the minutes it missed — in order, from the provider's recent
bars — and continues live. A crash, a killed container or a lost database
connection is recovered the same way: every minute is committed atomically, so
the database always ends at a minute boundary.

Replay time grows with the length of the session (every logged minute is
replayed); start a new session now and then if restarts get slow.

## 16.6 Starting a new session

A session is resumed only under the conditions it began with
([12.7](12-strategy-lab.md#the-input-log-and-exact-replay)). After a change to
an instance (strategy code, parameters, instruments, timeframes, account
settings), an added, removed or disabled instance — in `lab.yaml` or
`instances.d/` — the instrument catalog, or `base_timeframe` /
`equity_snapshot_minutes`, resuming fails with *cannot be resumed: … — start a
new session: kterminal paper start --new-session*, naming each change; the
engine publishes the error in its status and retries every minute. Changes to
the `forward` section, to disabled instances or to an instance's `host` do not
end the session.

```bash
kterminal paper start --new-session      # foreground: end the open session, start a new one
kterminal paper end-session              # only end it; the next start begins a new one
# with Docker, while the engine retries in vain:
docker compose exec engine kterminal paper end-session   # the engine starts the new session
                                                         # at its next retry (within a minute)
```

`paper end-session` is refused while a runtime is running (stop it first);
after a refused resume the engine's runtime is not running, so it can be used
right away. Ending a session closes each open position at its instrument's
last processed price (an exit with reason `RUN_END`) and marks the run
`COMPLETED`. The new session provisions the dedicated accounts again (changed
settings become a new configuration version, new instances get their account)
and each account continues from its ledger balance. Results stay separable by
session (`run_id`) and by strategy version.

## 16.7 Kill switch

```bash
kterminal killswitch on --reason "CPI release"                      # GLOBAL
kterminal killswitch on --scope strategy --id demo_sma_fast --reason "review"
kterminal killswitch on --scope account --id <account uuid> --reason "drawdown" --close-positions
kterminal killswitch status
kterminal killswitch off [--scope … --id …] [--reason …]
```

While a switch covers an account, new entries are refused (risk decision
`KILL_SWITCH_ACTIVE`) and its resting entry orders are cancelled; exits, stop
moves and protective stops and targets keep working. `--close-positions` also
closes its open positions at the next bar's open (`FLATTEN` orders, exit
reason `KILL_SWITCH`). A change takes effect from the next processed minute.
Switches are stored in `kill_switches`, so they survive restarts and apply to
a new session from its first minute; each change is in the audit log
(`kterminal db verify-audit` checks its hash chain). Switching off is always
manual.

## 16.8 When something goes wrong

| Message / symptom | Cause | What to do |
|---|---|---|
| `SessionMismatchError` | The configuration, catalog or a strategy version changed since the session began | Revert the change, or end the session and start a new one (16.6) |
| `InstanceFileError` (*defined in both …*) | The same instance id in `lab.yaml` and an `instances.d/` file, or in two files | Rename or remove one of them |
| *Market data is not usable* (exit code 2) | The data source map or the market-data settings are invalid | Fix what the message lists (`kterminal data sources` shows the map) |
| Instrument `no_provider` | Not in the data source map, or none of its providers is usable here (`last_error` says why, e.g. no OANDA token) | Configure the provider, then start a new session so the instrument is warmed up |
| `SessionVerificationError` (*input log*, *ledger entries differ*, …) | Rows of the session or its candles were changed or deleted outside the runtime | Investigate (the audit log, `candles`); start a new session |
| *another paper runtime is already running* | The engine or another `paper start` holds the runtime lock | Stop the other one |
| *still has open trades from an earlier session* | A dedicated account has an open trade that no running session owns (every session closes its positions when it ends) | Investigate how it got there before trading the account again |
| Instrument `stale` | Provider errors or late bars (`last_error` says which) | Usually none: retried automatically; check the provider if it persists |
| Instance `FAULTED` | The strategy raised, hung or crashed (`system_errors`) | Fix it; the fix is a new strategy version, so a new session |
| `paper.commit_failed`, then stop | PostgreSQL unavailable | Restore the database and start again: the session resumes from the last committed minute |

## 16.9 Known limits

* The whole session is replayed on every restart (no state snapshots yet).
* Fills are the lab's bar-based paper fills ([12.3](12-strategy-lab.md#123-accounts),
  [13.3](13-phase3-pine-ports.md#133-what-the-engine-still-needs)): market orders at
  the next bar's open with spread, slippage and commission from the venue profile.
* A minute is processed without an instrument that has not delivered it
  `forward.batch_timeout_s` (20 s) after its close; that instrument's late bar
  is dropped. The session's input log, not the venue's later history, is what
  the session traded on.
* Do not import candles under a live provider's source name into the time span
  of an open session: replay would read them and refuse to resume (*input
  log*).
* Warm-up for strategies using `ctx.periods` is sized by reading their code
  for `ctx.periods.previous(...)` / `current(...)`; a strategy should still
  declare `meta.warmup_bars` with `period_warmup_bars`.
* The runtime was tested with fake providers on a fake clock and with the
  real provider classes answering through fake venues shaped like their
  documented APIs — not against the live venues, which this development
  environment cannot reach.

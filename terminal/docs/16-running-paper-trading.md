# 16. Running paper trading

The forward paper runtime trades every enabled instance in `config/lab.yaml`
on live, closed 1-minute bars, each in its own dedicated `Paper 50K` account,
and records everything in PostgreSQL every minute. How it works is described
in [12.7](12-strategy-lab.md#127-forward-sessions-the-lab-on-live-data); this
document is the operator's side. Nothing here can place a real order: fills
are simulated, no broker adapter is constructed, and LIVE accounts cannot be
created.

## 16.1 Before the first start

| Step | Command / file |
|---|---|
| Schema up to date | `kterminal db upgrade` (Docker: the `migrate` service does it) |
| Instances to trade | `config/lab.yaml` — `kterminal strategies list` shows them |
| Market data | Each instrument needs a provider (the data source map of the market-data layer, [15](15-market-data.md)); an instrument without one is reported `no_provider` and never trades |
| History (optional) | `kterminal data import-csv FILE --instrument XAUUSD --source <provider>` loads bars into `candles`. Warm-up uses stored candles of the instrument's live source, so import under the provider's name to save downloads |

`kterminal lab provision` is optional: starting a session provisions the
dedicated accounts itself.

## 16.2 Starting

| Where | How |
|---|---|
| Docker | The `engine` service runs the paper runtime as soon as it is the leader — nothing else to do. Without `config/lab.yaml` it runs without it |
| Foreground | `kterminal paper start [--warmup-days N]` — runs until Ctrl-C / SIGTERM |

Only one runtime may run against a database (an advisory lock): with the
engine running, `paper start` stops with *another paper runtime is already
running*. Stop the engine first, or let the engine do the work.

The first start creates the session: accounts are provisioned, each instance
is warmed up on recent history (`--warmup-days`, default 10, caps how far back
it reaches) and live trading starts at the current minute. Logs show
`paper.warmup` per instrument and `paper.session_started`.

## 16.3 Watching it

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
| `no_provider` | No provider is configured for it |

Logged events worth alerting on: `paper.feed.provider_error`,
`paper.feed.minute_missing`, `paper.feed.late_bar_dropped` (a bar that came
after its minute was processed — dropped, never processed out of order),
`paper.commit_failed`, `paper.runtime_failed`.

## 16.4 Stopping and restarting

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

## 16.5 Starting a new session

A session is resumed only under the conditions it began with. After a change
to `lab.yaml`, the instrument catalog or a strategy's code or parameters,
resuming fails with *cannot be resumed: … — start a new session: kterminal
paper start --new-session*, naming each change; the engine publishes the error
in its status and retries every minute.

```bash
kterminal paper start --new-session            # in the foreground
# with Docker:
docker compose stop engine
docker compose run --rm engine paper start --new-session   # Ctrl-C once it runs
docker compose start engine                                # resumes the new session
```

`--new-session` ends the open session first: each open position is closed at
its instrument's last processed price (an exit with reason `RUN_END`) and the
run is marked `COMPLETED`. The new session provisions the dedicated accounts
again (changed settings become a new configuration version, new instances get
their account) and each account continues from its ledger balance. Results
stay separable by session (`run_id`) and by strategy version.

## 16.6 Kill switch

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

## 16.7 When something goes wrong

| Message / symptom | Cause | What to do |
|---|---|---|
| `SessionMismatchError` | The configuration, catalog or a strategy version changed since the session began | Revert the change, or start a new session (16.5) |
| `SessionVerificationError` (*input log*, *ledger entries differ*, …) | Rows of the session or its candles were changed or deleted outside the runtime | Investigate (the audit log, `candles`); start a new session |
| *another paper runtime is already running* | The engine or another `paper start` holds the runtime lock | Stop the other one |
| *still has open trades from an earlier session* | A dedicated account has an open trade that no running session owns (every session closes its positions when it ends) | Investigate how it got there before trading the account again |
| Instrument `stale` | Provider errors or late bars (`last_error` says which) | Usually none: retried automatically; check the provider if it persists |
| Instance `FAULTED` | The strategy raised, hung or crashed (`system_errors`) | Fix it; the fix is a new strategy version, so a new session |
| `paper.commit_failed`, then stop | PostgreSQL unavailable | Restore the database and start again: the session resumes from the last committed minute |

## 16.8 Known limits

* The whole session is replayed on every restart (no state snapshots yet).
* Fills are the lab's bar-based paper fills ([12.3](12-strategy-lab.md#123-accounts),
  [13.3](13-phase3-pine-ports.md#133-what-the-engine-still-needs)): market orders at
  the next bar's open with spread, slippage and commission from the venue profile.
* A minute is processed without an instrument that has not delivered it 20 s
  after its close; that instrument's late bar is dropped. The session's input
  log, not the venue's later history, is what the session traded on.
* Market-data providers come from the market-data layer; this runtime was
  tested with fake providers on a fake clock, not against live venues.

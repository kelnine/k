# 3. Repository / Folder Structure

The terminal lives in `terminal/`, self-contained, next to the existing
KCharts charting app (which is untouched and keeps its GitHub Pages deploy).
Files marked ✅ exist (Phase 1–2); the rest show where later phases land.

```
k/                                   repository root
├── src/ bot/ feed/ …                KCharts charting app (existing)
├── .github/workflows/
│   ├── deploy.yml                   KCharts Pages deploy (existing)
│   └── terminal-ci.yml          ✅  lint · types · architecture · tests · docker build
└── terminal/
    ├── README.md                ✅  quick start
    ├── Makefile                 ✅  dev / test / lint / compose shortcuts
    ├── .env.example             ✅  every setting, no secrets
    ├── docs/                    ✅  this design (01–10 + appendices)
    ├── config/                  ✅  configuration as code (mounted read-only into containers)
    │   ├── lab.yaml             ✅    strategy instances, account defaults (Paper 50K), external strategies
    │   └── catalog/             ✅    `kterminal catalog validate | apply`
    │       ├── venues.yaml      ✅    exchanges, brokers, prop-firm platforms, data/signal sources
    │       ├── instruments.yaml ✅    canonical instruments + global aliases
    │       ├── listings/*.yaml  ✅    per-venue contract specs (tick, size, qty step, costs, symbols)
    │       ├── sessions.yaml    ✅    trading calendars, trading-day rules, session windows (DST-aware)
    │       ├── costs.yaml       ✅    spread / commission / slippage / funding / swap profiles
    │       └── venue_profiles.yaml ✅ which listing each account simulates per instrument
    ├── data/                        local Parquet market data (git-ignored)
    ├── deploy/
    │   ├── docker-compose.yml   ✅  postgres · api · engine · worker · caddy
    │   ├── docker-compose.dev.yml ✅ exposes Postgres on 127.0.0.1 for local dev
    │   └── caddy/Caddyfile      ✅  TLS, TradingView IP allow-list, body limits
    ├── dashboard/               ✅  (placeholder) React + Vite SPA — Phase 8
    └── backend/
        ├── pyproject.toml       ✅  deps, ruff, mypy, pytest, import-linter contracts
        ├── uv.lock              ✅
        ├── Dockerfile           ✅  multi-stage, non-root
        ├── alembic.ini              Phase 2
        ├── migrations/              Phase 2 (Alembic versions)
        ├── tests/
        │   ├── unit/            ✅
        │   ├── integration/     ✅  real Postgres (skipped when unavailable)
        │   ├── fixtures/        ✅
        │   └── parity/              Pine ↔ Python parity tests per strategy (Phase 3+)
        └── src/kterminal/
            ├── __init__.py      ✅  version
            ├── cli.py           ✅  `kterminal api | engine | worker | config …`
            │
            ├── core/            ✅  SHARED KERNEL — imports nothing else from kterminal
            │   ├── enums.py     ✅  TradingMode, SignalAction, Direction, OrderSide, …
            │   ├── ids.py       ✅  UUIDv7 (time-ordered) identifiers
            │   ├── clock.py     ✅  Clock protocol, SystemClock, SimulatedClock
            │   ├── errors.py    ✅  exception hierarchy
            │   ├── events.py    ✅  DomainEvent + async in-process EventBus
            │   ├── registry.py  ✅  generic plug-in Registry with package discovery
            │   └── canonical.py     ✅  canonical JSON + hashing (versions, fingerprints)
            │
            ├── config/          ✅  typed settings, LIVE-mode interlock
            ├── observability/   ✅  structlog JSON logging, correlation IDs, redaction (metrics: Phase 5)
            ├── db/              ✅  session, advisory locks, models.py, migrations/ (Alembic),
            │                        partitions.py, audit.py (hash chain), repositories/
            ├── domain/          ✅  pure domain model: timeframes, market (Bar/Quote), signals,
            │                        instruments (+futures roll), symbols, sessions, costs,
            │                        catalog, accounts
            │
            ├── marketdata/          (4)  aggregator.py ✅, synthetic.py ✅, providers/ (Phase 3/5)
            ├── indicators/          Pine-compatible ta.* functions (Phase 3)
            ├── strategy_engine/ ✅  (1)  base.py, context.py, series.py, book.py, model.py,
            │                             registry.py, instances.py, versioning.py, runner.py,
            │                             hosts.py (in-process + subprocess), testing.py
            ├── strategies/          STRATEGY PLUG-INS — one folder per strategy_id
            │   └── <strategy_id>/
            │       ├── __init__.py
            │       ├── strategy.py        the Strategy subclass
            │       ├── params.yaml        default parameters
            │       ├── README.md          logic, origin, porting notes
            │       ├── pine/original.pine reference Pine source
            │       └── tests/             golden + parity tests
            ├── risk/                (6)  sizing.py ✅, checks.py ✅ (Phase-2 checks); engine.py,
            │                             rules/, drawdown.py, monitor.py, killswitch.py (Phase 5)
            ├── brokers/             (8)  base.py ✅ (BrokerAdapter + capabilities); one module per
            │                             venue/platform: mt5_bridge, tradelocker, tradovate, … (9/10)
            ├── execution/           (7)  router.py, engine.py, orders.py (state machine),
            │                             positions.py, brackets.py, reconcile.py
            ├── analytics/           (9)  summary.py ✅; metrics.py, breakdowns.py, leaderboard.py (4)
            ├── backtest/            (2)  engine.py, fill_model.py, replay.py, results.py
            ├── paper/           ✅  (3)  account.py (paper account + fills + ledger), lab.py,
            │                             config.py, records.py, store.py, pg_store.py, demo.py
            ├── webhook/             (5)  schemas.py, validation.py, normalize.py,
            │                             idempotency.py, service.py
            ├── notifications/       (11) base.py (Notifier), telegram.py, policy.py,
            │                             templates.py, reports.py, delivery.py
            ├── api/                 ✅ (12) app factory, middleware, routes/{health ✅, webhooks,
            │                             accounts, strategies, trades, analytics, risk, system}
            └── runtime/             ✅  composition root: container.py, service.py (process
                                         lifecycle), engine.py, worker.py
```

## Conventions

* **One strategy = one folder** under `kterminal/strategies/`. Discovery is
  automatic; nothing else changes when a strategy is added. Strategies can
  also be shipped from a separate Python package via the `kterminal.strategies`
  entry-point group.
* **One broker = one module** under `kterminal/brokers/`, registered by name.
  Account configuration references the adapter by that name.
* **Ports live with their module** (`brokers/base.py`, `notifications/base.py`,
  `marketdata/base.py`, `strategy_engine/base.py`); concrete adapters are wired
  only in `runtime/`.
* **Tests mirror packages**: `tests/unit/<module>/…`. Anything touching the
  database is an integration test and runs against a real PostgreSQL in CI.
* **Architecture is tested**: `lint-imports` fails CI if a module imports
  something its layer forbids (see [01-architecture](01-architecture.md#allowed-dependencies-enforced-by-import-linter)).

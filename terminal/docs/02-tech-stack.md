# 2. Technology Stack

Python for everything that touches trading logic; TypeScript only for the
browser. Each choice below is the recommended production default along with
the reason and the alternative that was considered.

## 2.1 Backend

| Concern | Choice | Why | Considered |
|---|---|---|---|
| Language | **Python 3.12** | Best ecosystem for quant work (numpy, pandas/polars), easy to port Pine logic to, mature async I/O. Strategies are bar-based (seconds–hours), so Python's speed is not a constraint | Rust/Go — faster, but slows strategy iteration and porting |
| Web framework | **FastAPI** + Uvicorn | Async, Pydantic-native validation (critical for webhooks), OpenAPI generated for the dashboard client, WebSockets built in | Litestar (similar), Django (heavier, sync-first) |
| Schemas / validation | **Pydantic v2** | One model type for API payloads, signals, settings and risk configs; strict mode; fast | dataclasses + marshmallow |
| Settings | **pydantic-settings** | Typed env vars, `SecretStr`, Docker secrets directory support | dynaconf |
| ORM / SQL | **SQLAlchemy 2.0** (async) + **asyncpg** | Explicit SQL when needed, typed models, mature | SQLModel (thin layer over SA), raw asyncpg |
| Migrations | **Alembic** | Standard for SQLAlchemy, reviewable migration scripts | — |
| Database | **PostgreSQL 16** | ACID for the audit trail, `NUMERIC` for money, `JSONB` for snapshots, partitioning for time series, `LISTEN/NOTIFY` + `SKIP LOCKED` for a durable queue, advisory locks for leader election | TimescaleDB extension is a drop-in upgrade if candle/equity tables outgrow native partitioning |
| Queue / events | **Postgres transactional outbox** | Atomic "persist signal + enqueue" (no dual-write), durable, auditable, zero extra services. Throughput need is tiny | Redis Streams / RabbitMQ — added only if tick-level fan-out is ever needed |
| Scheduling | **APScheduler 3** (in `worker`) | Cron-style, timezone-aware daily/weekly reports | Celery beat (needs a broker) |
| HTTP client | **httpx** | Async, timeouts, used for Telegram and REST brokers | aiohttp |
| Logging | **structlog** → JSON on stdout | Structured, context-bound correlation IDs, redaction processor; stdlib logs routed through it | loguru |
| CLI | **Typer** | One entry point: `kterminal api / engine / worker / backtest / config` | click |
| Numerics | **Decimal** for money/prices; **numpy** for indicators; **pandas or polars** for analytics | Exact accounting where it matters, vector speed where it does not | float everywhere (accumulates accounting error) |
| Market-data storage | **Parquet** files for bulk history + Postgres `candles` for bars used in paper/live | Columnar, compressed, fast backtest loading; Postgres keeps the audit copy of bars that drove real decisions | Everything in Postgres (slower bulk scans) |
| Backtesting | **Custom event-driven engine** | The same strategy, risk and accounting code must run in backtest and live, including path-dependent prop rules (intraday trailing drawdown, daily loss with floating P&L) that vectorized frameworks cannot express | *NautilusTrader* — excellent production-grade event-driven engine with backtest/live parity; the strongest alternative, rejected for now because of its learning curve and because prop-rule modelling would still be custom. *vectorbt* remains useful for quick parameter research outside the terminal |
| Indicators | Own **Pine-compatible** functions (`kterminal.indicators`) | Porting fidelity: e.g. Pine's `ta.rma`/`ta.ema` are seeded with an SMA; `ta.atr` uses RMA. Matching these exactly is what makes parity tests pass | TA-Lib / pandas-ta (different seeding conventions → small but real divergences) |
| Telegram | **Direct Bot API over httpx** for delivery | Full control over retries, `retry_after` handling and rate limits; tiny surface | python-telegram-bot / aiogram — used later only if interactive bot features grow |
| Dependency mgmt | **uv** with committed `uv.lock` | Fast, reproducible installs, same lockfile in CI and Docker | Poetry |
| Quality | **ruff** (lint + format), **mypy --strict**, **pytest** (+ `pytest-asyncio`, `hypothesis` for risk-rule properties), **import-linter** (architecture contracts) | Catch errors before they reach money | — |

## 2.2 Frontend (Phase 8)

| Concern | Choice | Why |
|---|---|---|
| Framework | **React 18 + TypeScript + Vite** (single-page app) | The dashboard is an authenticated internal tool: no SEO or server rendering needed. A static bundle served by Caddy means no Node server in production, a smaller attack surface, and the same toolchain the repository already uses for KCharts |
| Server state | **TanStack Query** (+ WebSocket invalidation) | Caching, retries, live updates |
| Tables | **TanStack Table** | Trade history, leaderboard, logs — sorting, filtering, virtualization |
| Styling | **Tailwind CSS** with a dark terminal theme | Fast, consistent dense UI |
| Price charts | **KCharts canvas engine** (already in this repo, `src/engine`) | Candles with trade entry/exit/SL/TP markers; extracted into a shared package when the dashboard is built |
| Analytics charts | **Apache ECharts** | Equity curves, drawdown, distributions; handles large series, dark theme built in |
| API client | Generated from FastAPI's OpenAPI schema | Typed end to end |

Next.js was considered; it is a good fit for public, SEO-sensitive sites but
adds a Node runtime and a second backend-for-frontend to secure, with no
benefit for this use case.

## 2.3 Infrastructure

| Concern | Choice | Why |
|---|---|---|
| Containers | **Docker** (multi-stage, non-root, read-only root FS) | One image, several process roles |
| Orchestration | **Docker Compose** on a single VPS initially | Simple, adequate for one operator; the same images move to Kubernetes/Nomad later if needed |
| Reverse proxy / TLS | **Caddy 2** | Automatic HTTPS via Let's Encrypt, HSTS, a simple IP allow-list for the TradingView webhook path, request size limits, static file serving |
| Secrets | Env vars for dev; **Docker secrets** (`/run/secrets/*`) in production; optional Vault/SOPS/1Password later | Credentials never in git, never in images, never in TradingView alerts |
| Backups | Nightly `pg_dump` (encrypted, off-site) → later pgBackRest with WAL archiving for point-in-time recovery | The audit trail is the product |
| Monitoring | Prometheus metrics endpoint + Grafana (optional), Sentry (optional), heartbeat/dead-man alerts to Telegram | Know when the engine stops |
| CI | **GitHub Actions** — lint, type-check, architecture contracts, tests against a real Postgres, Docker build | Every push |
| Hosting | A VPS in a region near the broker's servers (e.g. London/New York for FX/metals, Chicago for CME futures) with NTP (chrony) | Timestamp validation depends on an accurate clock; latency is secondary for bar-based strategies |

## 2.4 Broker / data integrations (Phases 9–10, to be confirmed per venue)

| Use | Candidates | Notes |
|---|---|---|
| Demo broker (Phase 9) | **OANDA v20 practice** (FX, metals incl. XAU/USD, CFDs), Alpaca paper (US equities/crypto), Interactive Brokers paper (via IB Gateway), Binance Spot testnet (crypto) | OANDA practice is the natural first target for XAUUSD-style strategies: free, REST + streaming, separate practice environment |
| Futures prop firms | Platforms commonly used by futures evaluations: Tradovate, Rithmic, ProjectX-based APIs | API access, automation policy and fees differ per firm — verify before building |
| CFD prop firms | MetaTrader 5, cTrader Open API, DXtrade, Match-Trader | The official `MetaTrader5` Python package runs on Windows only → needs a small Windows bridge service |
| Historical data | CSV/Parquet import (TradingView exports, broker history APIs, Dukascopy for FX/metals) | Check each source's licence; TradingView does not offer a data API |

**Prop-firm policy warning:** many firms restrict or prohibit fully automated
trading, copy trading between accounts, or specific practices (e.g. HFT,
news trading). Every prop adapter will carry a documented policy checklist and
the rules will be encoded in that account's risk profile.

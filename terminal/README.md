# K Terminal

A modular algorithmic trading terminal: test indicators and strategies
independently, compare them under identical market and risk conditions,
forward-test them on simulated prop-style accounts, receive TradingView
signals, report to Telegram — and, only after validation, execute on demo,
prop-firm and live accounts.

> **Status: Phase 1 of 11 — architecture & foundation.** No trading logic yet.
> LIVE execution is disabled by default and guarded by multiple interlocks.

## Design

Start with [`docs/`](docs/README.md):
[architecture](docs/01-architecture.md) ·
[tech stack](docs/02-tech-stack.md) ·
[repository layout](docs/03-repository-structure.md) ·
[database schema](docs/04-database-schema.md) ·
[strategy interface](docs/05-strategy-interface.md) ·
[TradingView webhook](docs/06-tradingview-webhook.md) ·
[risk engine](docs/07-risk-engine.md) ·
[Telegram](docs/08-telegram.md) ·
[security](docs/09-security.md) ·
[roadmap](docs/10-roadmap.md) ·
[metric definitions](docs/appendix-a-metrics.md)

## What Phase 1 delivers

| Area | Delivered |
|---|---|
| Structure | `kterminal` Python package with one sub-package per architecture module; React dashboard placeholder; deploy configs |
| Architecture enforcement | import-linter contracts: layered modules, sandboxed strategies, pure risk engine, broker access only from the execution layer |
| Core kernel | Trading vocabulary enums, UUIDv7 IDs, injectable `Clock` (system + simulated), error hierarchy, deterministic failure-isolated event bus, plug-in `Registry` with package discovery |
| Configuration | Typed settings (`KT_*` env vars, `.env`, Docker-secret `*_FILE` files); LIVE can never be the default mode; enabling LIVE requires an exact acknowledgement phrase; production refuses default credentials and non-JSON logs |
| Logging/audit | Structured JSON logs, correlation IDs bound per request, secret redaction (keys, DSNs, bot tokens, bearer tokens, `"secret":` fields) for our logs and third-party logs |
| Processes | `kterminal api` (FastAPI: `/health/live`, `/health/ready`, `/api/v1/system/info`), `kterminal engine` (Postgres advisory-lock leader election — exactly one active engine, automatic standby takeover, stops if leadership is lost), `kterminal worker` |
| Containers | Multi-stage non-root image; Compose stack (Postgres on an internal network, Docker secrets, read-only containers, dropped capabilities); Caddy with automatic HTTPS and the TradingView IP allow-list |
| CI | Ruff, mypy `--strict`, architecture contracts, unit + integration tests on real PostgreSQL, image build and smoke test, Compose and Caddyfile validation |

## Quick start (local development)

Requirements: [uv](https://docs.astral.sh/uv/), PostgreSQL 16 (or Docker).

```bash
cd terminal
cp .env.example .env            # adjust KT_DATABASE__* if needed
make install                    # uv sync
make dev-db                     # optional: PostgreSQL in Docker on 127.0.0.1:5432
make config                     # validate configuration (incl. LIVE interlocks)
make api                        # http://127.0.0.1:8000/api/v1/docs
make engine                     # in another shell — start a second one to see standby
make check                      # lint, types, architecture contracts, tests
```

`make test` runs integration tests against `TEST_DB`
(default `postgresql://kterminal:kterminal@localhost:5432/kterminal_test`);
without a reachable database they are skipped.

## Full stack (Docker Compose)

```bash
cd terminal
make secrets                    # generates deploy/secrets/postgres_password (git-ignored)
KT_PUBLIC_DOMAIN=terminal.example.com make up
make logs
```

Only Caddy publishes ports (80/443). In Phase 1 the only public route is the
(not yet implemented) TradingView webhook path, restricted to TradingView's
source IPs; everything else returns 404 until the authenticated dashboard
lands in Phase 8.

## Adding things later — without touching the core

* **Strategy** → new folder `backend/src/kterminal/strategies/<strategy_id>/`
  ([spec](docs/05-strategy-interface.md)), or declare an external TradingView
  strategy in `config/strategies.yaml`.
* **Broker / prop adapter** → new module in `backend/src/kterminal/brokers/`
  implementing `BrokerAdapter`.
* **Risk rule / notifier / data provider** → register a plug-in in its module.

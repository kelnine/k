# K Terminal — Design Documents

The design for a modular algorithmic trading terminal: test strategies
independently, compare them under identical conditions, forward-test them on
simulated prop-style accounts, receive TradingView signals, report to
Telegram, and — only after validation — execute on demo, prop and live
accounts.

| # | Document | Contents |
|---|---|---|
| 1 | [Architecture](01-architecture.md) | Principles, modular monolith, process roles, the 13 modules, dependency rules, signal/backtest flows, accounts, events, time & precision, modes |
| 2 | [Technology stack](02-tech-stack.md) | Backend, frontend, infrastructure, broker/data candidates — with reasons and alternatives |
| 3 | [Repository structure](03-repository-structure.md) | Folder layout and conventions |
| 4 | [Database schema](04-database-schema.md) | PostgreSQL tables, audit trail, "explain this trade" query |
| 5 | [Strategy interface](05-strategy-interface.md) | `Signal` model, Strategy SDK, registration, external strategies, Pine porting |
| 6 | [TradingView webhook](06-tradingview-webhook.md) | Endpoint, payload, validation pipeline, idempotency, alert templates |
| 7 | [Risk engine](07-risk-engine.md) | Rule pipeline, sizing, prop-style drawdown models, monitoring, kill switch |
| 8 | [Telegram](08-telegram.md) | Outbox-based delivery, events, templates, scheduled reports |
| 9 | [Security](09-security.md) | Threat model, controls, LIVE interlocks |
| 10 | [Roadmap](10-roadmap.md) | Phases 1–11, exit criteria, live promotion gates |
| 11 | [Instruments, sessions & costs](11-instruments-sessions-costs.md) | Instrument catalog, symbol mapping, sessions and time zones, transaction costs |
| 12 | [Strategy lab](12-strategy-lab.md) | Running N strategies side by side on separate paper accounts, isolation audit |
| 13 | [Phase 3 Pine ports](13-phase3-pine-ports.md) | Received scripts, strategies to port, engine prerequisites, order of work, open decisions |
| 14 | [Indicators](14-indicators.md) | Pine-parity `ta.*` library: streaming classes, seeding, na and tie rules, SAR/SuperTrend/VWAP details, what is still unverified |
| A | [Metric definitions](appendix-a-metrics.md) | Exact formulas used by analytics and the leaderboard |

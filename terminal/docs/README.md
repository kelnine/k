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
| 15 | [Market data](15-market-data.md) | Data source map, venue providers (Binance, Bybit, Coinbase, Hyperliquid, OANDA, CSV), limits, geo-restrictions, CSV/TradingView import, `kterminal data` |
| 16 | [Running paper trading](16-running-paper-trading.md) | Runbook: starting, watching, restarting and replacing forward paper sessions; the kill switch; troubleshooting |
| 17 | [Dashboard](17-dashboard.md) | The web terminal: first user, sign-in and roles, pages, metrics, kill switches from the browser, the `/api/v1` read API, Caddy deployment |
| S1·S7·S8 | [Ports: EliteAlgo, SuperTrend flip, PSAR](ports-s1-s7-s8.md) | The first Pine ports: strategies, `instances.d` instances, doc 13 decisions applied, what is and is not verified |
| S2·S3 | [Ports: Opening range breakout, Smart Money sniper](ports-s2-s3.md) | NY and London ORB with the EMA 9/20 filter and the 16:00 flatten; the script 5 sniper (BOS + score, 2R): strategies, `instances.d` instances, doc 13 decisions applied, what is and is not verified |
| S4·S5 | [Ports: ICT Sweep Models B and A](ports-s4-s5.md) | Script 2's sweep → MSS → displacement-FVG limit models: strategies, `instances.d` instances, doc 13 decisions applied, what is and is not verified |
| A | [Metric definitions](appendix-a-metrics.md) | Exact formulas used by analytics and the leaderboard |

# 10. Development Roadmap

Each phase ends with working, tested, documented software and an explicit
exit criterion. No phase starts before the previous one's exit criteria are
met. LIVE execution is the very last step.

| Phase | Scope | Key deliverables | Exit criteria |
|---|---|---|---|
| **1. Architecture & repository** ✅ | Design docs, repo layout, tooling, CI, Docker, config, logging, core kernel, process skeletons | `terminal/` tree; `kterminal api/engine/worker/config` CLI; health endpoints; LIVE interlocks 1–3; structured logging with redaction; event bus; plug-in registry; advisory-lock leader election; import-linter contracts; Compose + Caddy | CI green (lint, types, contracts, tests on real Postgres, Docker build); `docker compose up` serves `/health/ready` |
| **2. Database, instruments & strategy lab** ✅ | Production schema (SQLAlchemy + one Alembic migration, monthly partitions, hash-chained audit log); canonical instrument catalog (instruments → venues → listings, aliases, futures contract roll, venue profiles); sessions/time zones with DST; transaction-cost models (spread, commission, slippage, funding, swap); `Signal` standard; Strategy SDK, registry/discovery, instances, versions; in-process and subprocess hosts; theoretical book; multi-timeframe aggregation; paper accounts with sizing, fills, costs and ledger; the lab and `kterminal lab demo` | Migrations round-trip and match the models; catalog validates; two strategies run simultaneously into two independent Paper 50K accounts with an isolation audit from recorded rows; random-walk test shows no fill/look-ahead bias |
| **3. Example strategy & backtesting engine** | Pine-compatible indicators; Parquet/CSV data import; `SimulatedClock`; `SimulatedBroker` + fill model (spread, slippage, commission, intrabar SL/TP); minimal risk engine (sizing + core rules); `backtest_runs`; one example strategy (ported from one of your Pine scripts if available) with golden + parity tests; signal-replay mode | Backtest of the example strategy is reproducible bit-for-bit; parity with TradingView trade list within one tick |
| **4. Analytics & leaderboard** | All metrics in appendix A; breakdowns by strategy/symbol/timeframe/session/day/week/month/direction; leaderboard; comparison runner (N strategies × identical account + profile); CLI + JSON/CSV export | Metrics verified against hand-calculated fixtures; leaderboard over ≥ 2 strategies |
| **5. Paper / forward trading** | Live market-data provider(s); bar aggregator; full risk engine (doc 07) incl. daily loss, trailing/static DD, sessions, kill switch, equity monitor; `PaperBroker`; virtual accounts per strategy; allocations; reconciliation of theoretical vs. account positions | 2 weeks of unattended paper running with zero unhandled errors; every rule covered by unit + property tests |
| **6. TradingView webhook receiver** | Endpoint per doc 06; secrets + rotation; IP allow-list; rate limiting; idempotency + cool-down; `test` mode; external strategy config | Load test (100 req/s burst) with p99 < 250 ms; fuzzed payload tests; real TradingView alert end-to-end into a paper account |
| **7. Telegram** | Notifier port + Telegram adapter; outbox delivery loop; policy/routing/de-dupe; all event templates; daily & weekly reports; heartbeat alerts | All events in doc 08 delivered in a staging chat; Telegram outage simulation causes zero trading impact |
| **8. Dashboard** | React SPA (dark terminal theme): Overview, Strategies, Strategy Comparison, Accounts, Open Positions, Trade History (with "explain trade"), Analytics, Prop Rules, TradingView Signals, Telegram, System Logs, Settings; auth (argon2id + TOTP), RBAC, WebSocket live updates | Usable end-to-end without CLI for daily operation; auth & RBAC tests |
| **9. Demo broker** | `BrokerAdapter` implementation for the first demo venue (proposed: OANDA practice); symbol mapping; bracket orders; order-state reconciliation; reconnect; slippage tracking paper vs. demo | 4 weeks of demo trading with full reconciliation and zero orphaned orders |
| **10. Prop-firm / live adapters** | Adapters for the chosen prop platform(s) and live broker; per-firm risk-profile templates; policy checklist; LIVE interlocks 4–7; strategy promotion workflow | Adapters pass the shared adapter conformance test-suite against demo environments |
| **11. Live execution** | Enable LIVE for one validated strategy on one account with minimum size; daily reconciliation review | Promotion gates met (below) and explicit written sign-off |

## Live promotion gates

Default gates (configurable, recorded in `strategy_promotions` as evidence):

| Gate | PAPER → DEMO | DEMO → LIVE_APPROVED |
|---|---|---|
| Minimum forward-test duration | 30 trading days | 30 trading days on demo |
| Minimum closed trades | 50 | 30 |
| Profit factor | ≥ 1.2 | ≥ 1.2 |
| Max drawdown | ≤ profile limit × 50 % | ≤ profile limit × 50 % |
| Expectancy | > 0 R | > 0 R |
| Drift vs. backtest | Win rate and avg R within ±25 % of the backtest | Avg slippage within the fill-model assumption |
| Risk-engine integrity | 0 rule violations, 0 unhandled errors | Same + 0 reconciliation mismatches |
| Operational drills | — | Kill switch drill, broker disconnect drill, engine failover drill passed |
| Human sign-off | — | Required |

## Working agreement for strategy intake

When you provide an indicator or Pine strategy, it is integrated as follows,
independently of all others:

1. Add it as an `EXTERNAL` strategy (webhook) so it can be forward-tested
   immediately, *and/or*
2. Port it to an `INTERNAL` Python strategy in its own folder with the
   original Pine source kept alongside, golden tests, and a parity test against
   TradingView's trade list.
3. Backtest it on the shared data set with the shared risk profile, add it to
   the leaderboard, and give it its own Paper 50K account.

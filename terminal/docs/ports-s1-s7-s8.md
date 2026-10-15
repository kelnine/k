# Ports S1, S7, S8 — EliteAlgo, SuperTrend flip, 200 EMA PSAR

Three of the Phase 3 strategies ([doc 13 §13.2](13-phase3-pine-ports.md#132-strategies-to-port))
are ported to Python and configured to paper trade on live data. Each is a
plug-in in `backend/src/kterminal/strategies/<id>/` whose README holds the
rules with the Pine line numbers, the params, every deviation from the script
and the parity notes; this page is the overview.

| Doc 13 | Strategy id | Script | Trades | Script defines |
|---|---|---|---|---|
| S1 | `elitealgo_ema_confluence` | 9 · EliteAlgo v32 (replica+) | EMA 8/21 cross with ≥ 4 of 7 checks, EMA200 filter, shared 5-bar cooldown; stop 1.5 ATR(14), target 2R | entry, stop, target |
| S7 | `supertrend_flip` | 10 · Jetstream v2 | SuperTrend (10, 3) flip; BUY+/SELL+ (WaveTrend wt1 beyond zero) as the strong-only variant | entry |
| S8 | `psar_ema200` | 4 · Combined SMC Suite (PSAR section, rebuilt by its author from screenshots) | SAR crossing the close, with close beyond the EMA200 and ADX(14, 14) > 20; exit on the opposite flip | entry, flip exit |

All three decide on closed bars, return their signals with `ctx.long/short`,
`ctx.exit_*` and `ctx.move_sl`, and put the script's own values in the signal
metadata: the Pine variable (`pine_signal`), the label or marker text
(`trigger`) and the indicator values behind it, for "explain this trade".
They use `kterminal.indicators` only ([doc 14](14-indicators.md)), one object
per Pine call site, updated on every bar.

## Instances

`config/instances.d/<strategy id>.yaml` declares them; forward paper trading
loads them with `lab.yaml` ([12.7](12-strategy-lab.md#which-instances-trade)).
Every instance trades the 14 instruments of doc 13 D1 (XAUUSD, XAGUSD, NAS100,
US30, US500, MNQ, EURUSD, GBPUSD, BTCUSD, SOLUSD, NEARUSD, ZECUSD, HYPEUSD,
PUMPUSD) on its own Paper 50K account with `max_open_positions: 14`, one
position per instrument (D10).

| Instance | Timeframe | Variant |
|---|---|---|
| `elitealgo_ema_confluence_main_5m`, `…_main_15m` | 5m, 15m | script defaults; an opposite signal in a trade is ignored (D4) |
| `elitealgo_ema_confluence_reverse_5m`, `…_reverse_15m` | 5m, 15m | an opposite signal reverses at the next open (D4 variant) |
| `supertrend_flip_all_5m`, `…_all_15m` | 5m, 15m | every flip; stop at the line ∓ 1 ATR(10) (D5) |
| `supertrend_flip_strong_5m`, `…_strong_15m` | 5m, 15m | BUY+/SELL+ only, exit on any opposite flip (D11) |
| `supertrend_flip_trail_5m`, `…_trail_15m` | 5m, 15m | every flip; stop on the line, trailed every bar (D5 variant) |
| `psar_ema200_main_15m`, `psar_ema200_main_5m` | 15m, 5m | stop at the SAR printed on the signal bar (D5) |
| `psar_ema200_trail_15m`, `psar_ema200_trail_5m` | 15m, 5m | stop on the projected SAR, trailed every bar (D5 variant) |

## Decisions applied

The user did not answer doc 13 §13.6, so every default applies.

| Decision | S1 | S7 | S8 |
|---|---|---|---|
| D3 next-open fills | levels from the signal close; entry skipped when the fill bar opens at or beyond the stop or target; a stop or target not beyond the entry after tick rounding is not traded (a persisted `NO_TRADE` with the reason) | same (stop only: no target) | same (stop only) |
| D4 opposite signal | ignore until flat; `reverse` instances | stop and reverse: exit, then the new side, at one open | stop and reverse; flat when the new side's filters fail, as the script |
| D5 exits | the script's bracket | exit on the closed-candle flip; protective stop 1 ATR beyond the line; trailed-line variant | exit on the closed-candle flip; stop at the signal bar's SAR; trailed projected-SAR variant |
| D8 trading day | VWAP restarts at 17:00 New York (00:00 UTC crypto) | — | — |
| D9 volume | runs everywhere; `metadata.bar_source` names the feed, so tick-volume signals (OANDA) are labelled | — | — |
| D10 / D11 | 5m, 15m; two policies | 5m, 15m; all and strong-only | 15m plus 5m |
| D13 | script defaults | script defaults | script defaults |

Not run: S7's 4H higher-timeframe filter (off by default in the script) needs
4H bars on the instrument's session grid, which the market-data layer does not
build yet (doc 13 P5, open).

## What is verified, and what is not

| Check | Where |
|---|---|
| Golden scenarios from hand-built bars: each rule fires, each filter blocks, the D3/D4/D5 behaviour, cooldown counting, VWAP anchors across the 17:00 New York rollover in winter and summer, at 00:00 UTC for crypto and after a weekend | `tests/unit/strategies/<id>/test_strategy.py`, `…/test_vwap_anchor.py`, `…/test_state.py`, `…/test_rules.py` |
| An independent transcription of each script's lines, run against the port on long synthetic series (several seeds and inputs): identical signals and levels | `tests/unit/strategies/<id>/test_reference.py` |
| Every instance of each `instances.d` file loads, resolves against the real catalog and runs side by side in the lab on synthetic data without a fault | `tests/unit/strategies/<id>/test_instances.py` |
| The signals and their metadata are stored in PostgreSQL exactly as computed; the accounts audit clean | `tests/integration/strategies/test_pine_ports_postgres.py` |

**Not verified:** parity with TradingView (doc 13 §13.4 step 2). TradingView
and the market-data APIs are not reachable from the development environment
and no chart exports were provided, so no signal of these ports has been
compared with a chart and none has run on live bars yet. Every point listed
as unverified in [doc 14 §14.6](14-indicators.md#146-evidence-and-what-is-still-unverified)
applies.

## Warm-up

`warmup_bars` is 1000 for S1 and S8 (EMA200 and the Wilder averages) and 500
for S7. The forward runtime warms each instrument up on at most
`forward.warmup_days` (default 10) of history: enough for the 5m instances,
not for 1000 bars of 15m on markets that close at weekends (about 21 days).
Those instances log `paper.warmup_short` and start on a less converged EMA200.

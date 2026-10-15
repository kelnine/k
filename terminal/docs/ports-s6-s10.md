# Ports S6, S10 — Script 1 CISD: after a liquidity sweep, and the MTF scanner

Two of the Phase 3 strategies ([doc 13 §13.2](13-phase3-pine-ports.md#132-strategies-to-port))
come from script 1, "Breakout Targets + ICT Levels + CISD". The script has two
different CISD models — the main-chart one and the one its MTF scanner runs per slot
timeframe — and both are ported, each as its own strategy:
`backend/src/kterminal/strategies/cisd_sweep/` (S6) and `…/cisd_scanner/` (S10). Their
READMEs hold the rules with the Pine line numbers, the params, every deviation from the
script and the parity notes; this page is the overview. The range breakout,
trendlines, zones and opens of the same script stay display only (doc 13 D12).

| Doc 13 | Strategy id | Sweep that arms a CISD | Filters | Script defines |
|---|---|---|---|---|
| S6 | `cisd_sweep` | trade-through of PDH/PDL, PWH/PWL, PMH/PML (`ctx.periods`), of the last completed Asia 20:00-00:00, London 02:00-05:00 or NY AM 09:30-12:00 high/low (New York, only outside the session, only on charts ≤ 60m), or a break of the latest 5/5 pivot; never retired, any same-side sweep clears the pivot | body ≥ 0.3 × `nz(ATR14)`, sweep within 12 bars, signal window Any time / NY AM / London + NY AM (…) | entry level, stop, TP1/TP2 |
| S10 | `cisd_scanner` | a break of the latest 3/3 swing only | body ≥ 0.3 × `nz(ATR14)`, sweep within 12 bars; A+ = the 15m, 1h and 4h swing-break biases agree (read with `ctx.series(tf, tradingview_lag=True)`, like `lookahead_on` + `[1]`) | entry level, stop, TP1/TP2 |

Both models signal on a close through the open of the latest run of opposing closes
(the CISD level); a close through the level consumes it even when a filter fails. The
stop is the extreme of that run through the CISD bar — often inside the sweep wick —
and TP1/TP2 are 1R/2R from the level. They share the run tracker
(`cisd_sweep/runs.py`) and the order handling (`cisd_sweep/orders.py`), so S10's
version includes `cisd_sweep`'s code.

## How the script's trade maps onto the lab

| Script | Lab |
|---|---|
| Entry printed at the CISD level; the signal candle has already closed beyond it; no order, no fill check (the tracker counts from the signal bar) | doc 13 D7: a resting **LIMIT** at the level, expiring after 12 bars, cancelled (`EXIT_*` of the order) on the first bar after the signal on which TP1 trades before the fill; S6 also runs a market-at-next-open comparison instance with the script's levels (D3: skipped when the close or the next open has passed them) |
| TP1 and TP2, no sizing split; the stop never moves | one target per instance (TP1-only, TP2-only), the stop unchanged |
| A new CISD overwrites the tracked trade, without an exit price | doc 13 D4 replace: the resting order is cancelled, the open trade exits at the next open and the new CISD enters on the same bar (market mode reverses on an opposite CISD) |
| S6's tracker stops after 4,500 bars | an `EXIT_*` with reason `SESSION_CLOSE` |

Signals carry the script's numbers in their metadata: `trigger` (the alert titles
`Bullish CISD` / `Bearish CISD`, `Scanner: new signal` / `Scanner: new A+ signal`,
and `order cancelled`, `trade replaced`, `tracking ended`), `pine_signal`
(`bullCisd`/`bearCisd`, `scanCisd`), the CISD level, run extreme and length, body, ATR
and threshold, the sweep (bar, bars ago, the levels it took with their prices), every
live level (S6), the A+ grade and each higher slot's bias and latest signal (S10), the
scanner's alert text, and the unrounded script entry, stop, TP1, TP2 and R.

## Instances

`config/instances.d/cisd_sweep.yaml` and `cisd_scanner.yaml` declare them; forward
paper trading loads them with `lab.yaml` ([12.7](12-strategy-lab.md#which-instances-trade)).
Every instance trades the 14 instruments of doc 13 D1 on 5m on its own Paper 50K
account with `max_open_positions: 14`, one position per instrument (D10).

| Instance | Signals | Entry | Target |
|---|---|---|---|
| `cisd_sweep_any_tp1_5m` / `_tp2_5m` | S6, any time (script default) | limit | TP1 / TP2 |
| `cisd_sweep_nyam_tp1_5m` / `_tp2_5m` | S6, NY AM 09:30-12:00 | limit | TP1 / TP2 |
| `cisd_sweep_lonny_tp1_5m` / `_tp2_5m` | S6, London 02:00-05:00 + NY AM | limit | TP1 / TP2 |
| `cisd_sweep_any_market_5m` | S6, any time | market at the next open | TP2 |
| `cisd_scanner_plain_tp1_5m` / `_tp2_5m` | S10, every 5m signal (15m/1h/4h context) | limit | TP1 / TP2 |
| `cisd_scanner_aplus_tp1_5m` / `_tp2_5m` | S10, A+ only | limit | TP1 / TP2 |

## Decisions applied

The user did not answer doc 13 §13.6, so every default applies.

| Decision | S6 / S10 |
|---|---|
| D3 | market comparison only: no trade when the stop or target is not beyond the signal close (persisted `NO_TRADE`), skipped when the next open has passed either (`skip_entry_beyond_levels` in the meta); limits: no trade when a level is on the wrong side after tick rounding |
| D4 | replace (script 1): cancel or exit, then enter, on one bar; the market comparison reverses on an opposite CISD (`on_opposite_signal: reverse`). In limit mode an opposite CISD exits at the next open rather than through the engine's resting reversal, which would keep the old trade until the new limit fills (README) |
| D7 | limit at the CISD level, 12-bar expiry, cancelled if TP1 trades first; TP1-only and TP2-only instances; the S6 market comparison |
| D8 | PDH/PWH/PMH on the catalog's trading day: 17:00 New York, 00:00 UTC for crypto |
| D10 / D11 | 5m, all 14 instruments; S6 windows Any time, NY AM, London + NY AM; S10 plain and A+ |
| D13 | script defaults |

## What is verified, and what is not

| Check | Where |
|---|---|
| Golden scenarios on hand-built New York 5m tapes: each rule fires (pivot sweep, run, CISD, level, stop inside the sweep wick, TP2 fill) and each blocking rule blocks (no sweep, a sweep 13 bars back, a weak close that consumes the level, a doji ending the run, the signal windows, the ATR warm-up quirk); session levels only after their session (winter and summer), the trade-through rule, levels never retired, a pivot cleared by a session sweep, London on the night the clocks go forward, yesterday's NY AM range before 09:30, crypto sessions on Saturday, PDH/PWH at 17:00 New York and UTC midnight | `tests/unit/strategies/cisd_sweep/test_rules.py`, `test_sessions.py` |
| Every applied decision: limit fill and targets, 12-bar expiry, TP1-first cancel (and not on the signal bar), replace of an order, of a same-direction and of an opposite trade, the market comparison's next-open fill, D3 skips and reverse, an untradable CISD still ending the trade, the 4,500-bar exit; params; determinism | `…/cisd_sweep/test_decisions.py` |
| An independent procedural transcription of the main model's Pine lines (sessions by wall-clock minute, periods on the trading day, pivots by window, Wilder ATR), run against S6 on 41-70-day synthetic 5m runs across the clock change, round the clock and with closed weekends, on 5m/15m/1h/4h, for every input: the same CISDs on the same bars with the same level and stop; PMH/PML sweeps included | `…/cisd_sweep/test_reference.py` |
| S10: an A+ short under bearish 15m/1h/4h biases, a long against them, a disabled slot, a 4h break not yet visible (lookahead_on + [1]), the 3/3-only sweep where S6 has none, a session sweep that S10 ignores, the shared D7 orders; and an independent transcription of `scanCisd`, the slot bars and the A+ grade on two-week synthetic 1m runs, for every input | `tests/unit/strategies/cisd_scanner` |
| Every instance of both `instances.d` files loads, resolves against the real catalog and runs side by side in the lab on synthetic data without a fault | `…/cisd_sweep/test_instances.py`, `…/cisd_scanner/test_instances.py` |
| The signals and their metadata are stored in PostgreSQL exactly as computed; the accounts audit clean | `tests/integration/strategies/test_cisd_ports_postgres.py` |

**Not verified:** parity with TradingView (doc 13 §13.4 step 2). TradingView and the
market-data APIs are not reachable from the development environment and no chart
exports were provided, so no signal of these ports has been compared with a chart and
none has run on live bars yet. Known differences that remain by design: the accounts
fill limits and brackets on bid/ask while the theoretical book uses the mid (about 2 %
of cancels and replace exits find no order or position in the account in the synthetic
runs); the lab's 4h bars are UTC-aligned while TradingView anchors them to the symbol's
session, so S10's 4h bias and A+ grade can differ for every non-crypto instrument;
PWH/PWL and PMH/PML need about 16 and 64 days of warm-up (forward paper trading warms up
10 days by default, so those sweeps stay off until enough history has passed); the
session hour skipped when the clocks go forward is handled by the engine's rule, not
checked against TradingView.

## Warm-up

S6: `warmup_bars` 600 5m bars, plus `period_warmup_bars` for D, W and M added by
forward paper trading (capped by `forward.warmup_days`); S10: 36 **4h** bars (six
days round the clock), which fits the default 10-day cap.

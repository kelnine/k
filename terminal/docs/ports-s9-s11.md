# Ports S9, S11 — ICT Sweep Models C and D

Two of the Phase 3 strategies ([doc 13 §13.2](13-phase3-pine-ports.md#132-strategies-to-port))
come from script 2, "ICT Sweep + Order Flow Models [NY]": Model C (PD-array bias
+ IFVG / CISD) and Model D (order-flow absorption). Each is its own strategy in
its own package: `backend/src/kterminal/strategies/ict_model_c/` (S9) and
`…/ict_model_d/` (S11). Their READMEs hold the rules with the Pine line numbers,
the params, every deviation from the script and the parity notes; this page is
the overview. Models A and B of the same script are a separate port
([S4·S5](ports-s4-s5.md)); the three packages share no code.

| Doc 13 | Strategy id | Where | Trigger (closed 1m bars, New York, all days) | Script defines |
|---|---|---|---|---|
| S9 | `ict_model_c` | a 5m fair value gap of the side of the 1H PD-array bias (`f_pdBias`, persistent, starting at 0 = no trade), tapped at any time of day, its extreme at most 30 bars old | in 09:30-12:00: a 1m inversion FVG (any opposite 1m gap of the last 30 bars closed through) or a close beyond the zone's CISD level (a level test, not a cross); one trade a day | market entry at the signal close, stop at the zone extreme, target the nearest untaken 1H liquidity when ≥ 1R away, else 2R |
| S11 | `ict_model_d` | a 15m fair value gap (bullish = support, bearish = resistance) or a key level within 0.25 × ATR(14) (overnight 18:00-09:30 value area high/low and high/low, previous day high/low: support and resistance alike) | in 09:30-16:00: an aggressive selling bar (volume ≥ 1.5 × its 20-bar average, candle-estimate delta ≤ −30 %) at support, then within 10 bars an aggressive buying bar closing above its body (shorts mirror it); one trade at a time, no daily cap | market entry at the signal close, stop at the extreme since the selling bar, 2R |

Both read their higher timeframes as TradingView's `request.security(…,
lookahead_on)` with `[1]` sees them, through `ctx.series(tf,
tradingview_lag=True)`: the 1H bias and liquidity and the 5m zones (C), the 15m
zones (D). D's previous day comes from `ctx.periods` on the instrument's trading
day. D's "order flow" is a proxy — each bar's volume split by where it closed in
its range — and the script's intrabar (seconds data) source is not ported.

## How the script's trades map onto the lab

| Script | Lab |
|---|---|
| Entry recorded at the signal bar's close | doc 13 D3: a MARKET entry filled at the next open with the script's stop and target, skipped when that open is at or beyond either (`skip_entry_beyond_levels` in the meta); no trade when a level is on the wrong side after tick rounding (persisted `NO_TRADE`) |
| Stop and target checked by mid-price touch from the next bar, stop first | the theoretical book's and the account's bracket, both on the account's bid/ask on the same 1m bars |
| A trade still open at the model's next window start (09:30) is closed "neutral", without a price | `ctx.flatten()` (`SESSION_CLOSE`) on the window's first bar, filled at the next open, sent whenever a trade filled since the last time exit; an entry on the same bar is a replace (C) |
| D: the next setup waits until the script's own trade is closed | the strategy keeps the script's trade (`ScriptTrade`); when it opens a new one while the book still holds the previous one (closed by the script's unrounded level, not the book's), it flattens first and enters at the same open (D4 replace) |

Signals carry the script's numbers in their metadata: `trigger` (the alert
titles `C long` / `C short`, `D long` / `D short`, and `closed`, `window end`,
`replaced`), `pine_signal` (`evC`, `evD`, `closeTrade(0)`), and the unrounded
script entry, stop, target and R. C adds the bias and the 1h bar that set it,
the zone (edges, first candle, tap, extreme, CISD level), the inverted gap and
the draw on liquidity with its pivot; D adds the candidate (body edge, extreme,
volume, average, delta) with the zones and levels that put it at support or
resistance, the trigger bar's flow, ATR and tolerance, and every key level.

## Instances

`config/instances.d/ict_model_c.yaml` and `ict_model_d.yaml` declare them;
forward paper trading loads them with `lab.yaml`
([12.7](12-strategy-lab.md#which-instances-trade)). Every instance runs on 1m on
its own Paper 50K account, one position per instrument (D10).

| Instance | Instruments | Context | After the entry |
|---|---|---|---|
| `ict_model_c_main_1m` | the 14 of doc 13 D1 | 5m, 1h | held until stop, target or the next 09:30 (D6, as the script) |
| `ict_model_c_flat_1m` | the 14 | 5m, 1h | closed at the 12:00 window end (D6 variant) |
| `ict_model_d_main_1m` | MNQ, BTCUSD, SOLUSD, NEARUSD, ZECUSD, HYPEUSD, PUMPUSD (D9) | 15m | held until stop, target or the next 09:30 (D6, as the script) |
| `ict_model_d_flat_1m` | the same 7 | 15m | closed at the 16:00 window end (D6 variant) |

## Decisions applied

The user did not answer doc 13 §13.6, so every default applies.

| Decision | S9 / S11 |
|---|---|
| D3 | next-open fill with the script's stop and target, skipped when the open has passed either; no trade when a level is on the wrong side after tick rounding |
| D4 | one trade at a time (`on_opposite_signal: ignore`): C trades once a day; D has no daily cap and replaces a trade the book still holds after the script closed it |
| D6 | main instances hold as the script does and close at the next 09:30 (`SESSION_CLOSE`); `after_window: flat` variants close at the window end and do not enter on its last bar |
| D8 | D's PDH/PDL on the catalog's trading day: 17:00 New York (MNQ), 00:00 UTC for crypto |
| D9 | Model D only on MNQ and the crypto pairs |
| D10 / D11 | 1m; C on all 14 instruments, D on the 7 of D9; script defaults plus the D6 variant. C's `IFVG only` / `CISD only` triggers, its 15m setup FVG and Fixed RR target, and D's `HTF FVG only` / `Key levels only` modes are params, not yet instances |
| D13 | script defaults |

## What is verified, and what is not

| Check | Where |
|---|---|
| C golden scenarios on hand-built New York 1m tapes: the bias from a 1H FVG held (lagged one 1h bar), the draw on liquidity from an untaken 1H pivot, a 5m zone added one 1m bar after its third candle, a tap before 09:30, the CISD level test on the first window bar, the IFVG trigger, the short mirror; blocks: no bias, a zone against the bias, an extreme older than 30 bars, the zone used and one trade a day, a close through the zone, the window's edges; targets (DOL, min RR, fixed RR, no liquidity), the stop buffer; winter, summer, the first EDT Monday, Sunday for crypto | `tests/unit/strategies/ict_model_c/test_strategy.py` |
| D golden scenarios: absorption at a 15m zone and at a key level, the short mirror, a level as support and resistance, a zone one side only, the ATR tolerance; blocks: a close below the candidate, `dMaxBars`, the body edge, volume and delta thresholds, no volume at all, the window's edges and pre-09:30 candidates, one trade at a time; no daily cap and a new candidate on the bar that stops the previous trade; overnight levels by open time across both clock changes, PDH/PDL at 17:00 New York and UTC midnight | `tests/unit/strategies/ict_model_d/test_strategy.py`, `test_levels.py` |
| Every applied decision: D3 skips (open beyond the stop / target) and wrong-side levels after rounding, the hold flatten at the next 09:30 (and its `IGNORED` no-op when the trade already closed), the flat variant at 12:00 / 16:00 and no entry on the window's last bar, C's replace at the next window start, D's replace when the script closed a trade the book still holds; determinism | both `test_strategy.py` |
| The building blocks on hand vectors: `f_pdBias`, the zones and their tracking, the 1m gaps, run opens and IFVG list (C); the value area (first-max POC, ties up, edges, clamping), the overnight store, the candle-estimate flow, the script's trade, the zones and their touch (D) | `…/ict_model_c/test_blocks.py`, `…/ict_model_d/test_blocks.py` |
| Independent procedural transcriptions of the Pine lines (sessions by wall-clock minute, HTF bars by bucket, Wilder ATR, the value area, periods on the trading day), run against the ports on 12-14-day synthetic 1m runs across the November clock change for five input sets each (D on gold and bitcoin): the same trades on the same bars with the same unrounded entry, stop and target | `…/ict_model_c/test_reference.py`, `…/ict_model_d/test_reference.py` |
| Every instance of both `instances.d` files loads, resolves against the real catalog and runs side by side in the lab on synthetic data without a fault; every flatten that reached an account was approved; no book/account divergence | `…/ict_model_c/test_instances.py`, `…/ict_model_d/test_instances.py` |
| The signals and their metadata are stored in PostgreSQL exactly as computed (an ignored flatten as `IGNORED`, `NOTHING_TO_FLATTEN`); the accounts audit clean | `tests/integration/strategies/test_ict_models_c_d_postgres.py` |

**Not verified:** parity with TradingView (doc 13 §13.4 step 2). TradingView and
the market-data APIs are not reachable from the development environment and no
chart exports were provided, so no signal of these ports has been compared with
a chart and none has run on live bars yet. Model D's synthetic lab volume is
random and says nothing about how the model behaves on real MNQ or exchange
volume. Known differences that remain by design: entries fill at the next open
instead of the signal close; the accounts and the book resolve on bid/ask
while the script uses mid-price touches; the neutral close is a real exit at
the next open; C's persistent bias and stored lists depend on how much history
was loaded (TradingView's chart or the lab's warm-up).

## Warm-up

C: `warmup_bars` 168 **1h** bars (a week round the clock, 10,140 1m bars) for the
persistent bias, the 1H FVG lists and the untaken pivots. D: 200 **15m** bars
(about two days, 3,015 1m bars) for ATR, the volume average, the zones and a
complete overnight session, and `period_warmup_bars("D", "1m")` (3,001 bars)
for the previous day, which forward paper trading adds. Both fit
`forward.warmup_days` (16 in `lab.yaml`).

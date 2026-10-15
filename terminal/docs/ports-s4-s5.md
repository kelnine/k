# Ports S4, S5 — ICT Sweep Models B and A

Two of the Phase 3 strategies ([doc 13 §13.2](13-phase3-pine-ports.md#132-strategies-to-port))
come from script 2, "ICT Sweep + Order Flow Models [NY]": models A and B share
one sweep → MSS → displacement-FVG → resting-limit engine and are ported
together in `backend/src/kterminal/strategies/ict_sweep_models/` as two
strategies. Its README holds the rules with the Pine line numbers, the params,
every deviation from the script and the parity notes; this page is the
overview. Models C and D of the same script are separate ports.

| Doc 13 | Strategy id | Levels swept | Window (New York, all days) | Script defines |
|---|---|---|---|---|
| S4 | `ict_model_b` | high/low of the 1m bars opening 08:00-09:00, used only if < 24 h old; a close back inside is required | 09:00-12:00 | entry, stop, target |
| S5 | `ict_model_a` | the most recent untaken 15m swing high/low (`f_liqSwings(2)` via `request.security(..., lookahead_on)`), read with `ctx.series("15m", tradingview_lag=True)` | 20:00-02:00 | entry, stop, target |

Both run on closed 1m bars. After a wick through one level, a close beyond the
most recent 1m pivot (strength 2) formed before the sweep extreme is the MSS; a
displacement fair value gap (middle candle body ≥ 1.5 × its 20-bar average,
first candle at or after the extreme, middle candle at most 3 bars after the
MSS) arms a **LIMIT** at the gap's edge, with the stop at the sweep extreme
and the target at the opposite level, or 2R when that level is closer than
1R. A new extreme before arming restarts the search; sweeping the other level
flips the setup. One setup per window: after a fill or a miss the model idles
until its next window.

## How the script's order handling maps onto the lab

| Script | Lab |
|---|---|
| Limit armed at the bar close, checked from the next bar, filled at `min(open, entry)` | `ctx.long/short(order_type=LIMIT)`; the book and the accounts fill resting limits the same way (the accounts on bid/ask) |
| Target traded before the fill → setup dropped ("missed") | `EXIT_*` of the resting order on that bar |
| Unfilled setup dropped on the first bar after the window | the order carries `expires_after_bars` = the bars left in the window; if the window's last bars are missing, an `EXIT_*` cancels it on the first bar after the window |
| A filled trade runs past the window until its stop, its target or the model's next window start, where it is closed "neutral" | the book's bracket; at the next window start an `EXIT_*` with reason `SESSION_CLOSE` (D6 main) — or at the window end (D6 variant) |

Signals carry the script's numbers in their metadata: `trigger` (the script's
alert titles `A long setup`, `B short setup`, and `A missed`, `window end`,
`closed`), `pine_signal` (`evA`/`evB`, `closeTrade(0)`), the window's levels
and where they came from, the sweep extreme, the MSS level and bars, the FVG,
the unrounded script entry/stop/target and the planned RR.

## Instances

`config/instances.d/ict_model_a.yaml` and `ict_model_b.yaml` declare them;
forward paper trading loads them with `lab.yaml`
([12.7](12-strategy-lab.md#which-instances-trade)). Every instance trades the 14
instruments of doc 13 D1 on 1m on its own Paper 50K account with
`max_open_positions: 14`, one position per instrument (D10).

| Instance | After a fill |
|---|---|
| `ict_model_a_main_1m` | held until stop, target or the next 20:00 (D6, as the script) |
| `ict_model_a_flat_1m` | closed at the 02:00 window end (D6 variant) |
| `ict_model_b_main_1m` | held until stop, target or the next 09:00 (D6, as the script) |
| `ict_model_b_flat_1m` | closed at the 12:00 window end (D6 variant) |

## Decisions applied

The user did not answer doc 13 §13.6, so every default applies.

| Decision | S4 / S5 |
|---|---|
| D3 | does not apply to resting limits (they fill at the open when a bar opens through them, as in the script); a setup whose stop or target is not beyond the entry after tick rounding is a persisted `NO_TRADE` |
| D4 | one setup or trade at a time (`on_opposite_signal: ignore`), as the state machine implies |
| D6 | main instances hold as the script does and close at the next window start (`SESSION_CLOSE`); `after_window: flat` variants close at the window end |
| D10 / D11 | 1m, all 14 instruments; script defaults plus the D6 variant. The CE entry and Fixed RR target are params, not yet instances |
| D13 | script defaults |

## What is verified, and what is not

| Check | Where |
|---|---|
| Golden scenarios on hand-built New York 1m tapes: each rule fires (sweep, MSS, displacement FVG, close back inside, arming, fill, target, missed, window-end expiry, neutral close at the next window, flat variant) and each blocking rule blocks (stale range, no close back inside, `mssBar + 3`, FVG invalidation, extension and flip before arming, armed on the window's last bar, wrong-side levels after rounding); winter, summer, the first EDT Monday and the November fall-back night (a seven-hour 20:00-02:00 window); the TradingView one-bar lag of the 15m levels; Sunday sessions for crypto | `tests/unit/strategies/ict_model_a`, `…/ict_model_b`, `…/ict_sweep_models/test_engine.py` |
| An independent procedural transcription of the Pine lines, run against the port on 12-day synthetic 1m runs across the clock change (two seeds, six input sets): the same setups on the same bars with the same unrounded levels, the same fills, a cancel on every "missed" | `tests/unit/strategies/ict_sweep_models/test_reference.py` |
| Every instance of both `instances.d` files loads, resolves against the real catalog and runs side by side in the lab on synthetic data without a fault; the accounts approve every cancel and exit | `tests/unit/strategies/ict_model_*/test_instances.py` |
| The signals and their metadata are stored in PostgreSQL exactly as computed; the accounts audit clean | `tests/integration/strategies/test_ict_sweep_models_postgres.py` |

**Not verified:** parity with TradingView (doc 13 §13.4 step 2). TradingView and
the market-data APIs are not reachable from the development environment and no
chart exports were provided, so no signal of these ports has been compared
with a chart and none has run on live bars yet. Known differences that remain
by design: the accounts fill limits and brackets on bid/ask while the script
uses mid-price touches; the lab can take profit on the fill bar; the neutral
close is a real exit at the next open.

## Warm-up

Model A: `warmup_bars` 480 **15m** bars (five days round the clock, 7,215 1m
bars) for the 15m swing lists; Model B: 2,880 1m bars (two days). Both fit
the default `forward.warmup_days: 10`.

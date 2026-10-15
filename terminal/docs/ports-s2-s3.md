# Ports S2, S3 — Opening range breakout, Smart Money sniper

Two more Phase 3 strategies ([doc 13 §13.2](13-phase3-pine-ports.md#132-strategies-to-port))
are ported to Python and configured to paper trade on live data. Each is a
plug-in in `backend/src/kterminal/strategies/<id>/` whose README holds the
rules with the Pine line numbers, the params, every deviation from the script
and the parity notes; this page is the overview.

| Doc 13 | Strategy id | Script | Trades | Script defines |
|---|---|---|---|---|
| S2 | `orb_breakout` | 8 · FRVP + ORB + 9/20 EMA | First close beyond the 09:30-09:45 New York opening range (wick high/low of the bars opening in it), from the bar after the range until 16:00, with EMA 9 > EMA 20 for longs (< for shorts); at most one long and one short per range day; the London ORB as a variant | entry |
| S3 | `smc_sniper` | 5 · Smart Money Suite v4 [AlgoAlpha] | A close crossing the latest 40/40 swing (BOS, crosses evaluated before the swing update, levels never consumed) with ≥ Min Score of trend, structure, OB/FVG zone and momentum; stop beyond the opposite swing ± 0.5 ATR(14), target 2R | entry, stop, target |

Both decide on closed bars, return their signals with `ctx.long/short` and
`ctx.exit_*`, and put the script's own values in the signal metadata: the Pine
variable (`pine_signal`), the marker or alert title (`trigger`) and the values
behind it (the range and EMAs; the score, its four points, the zones holding
the close, the swing levels), for "explain this trade". They use
`kterminal.indicators` only ([doc 14](14-indicators.md)), one object per Pine
call site, updated on every bar, and Pine session strings as params
(`ctx.in_session`, [doc 05 §5.2.3](05-strategy-interface.md#523-session-windows-as-parameters)).

## Instances

`config/instances.d/<strategy id>.yaml` declares them; forward paper trading
loads them with `lab.yaml` ([12.7](12-strategy-lab.md#which-instances-trade)).
Each instance has its own Paper 50K account with `max_open_positions` equal to
its number of instruments, one position per instrument (D10).

| Instance | Timeframe | Instruments | Variant |
|---|---|---|---|
| `orb_breakout_ny_5m` | 5m | MNQ, NAS100, US30, US500 | script defaults; stop at the other side of the range, 2R, flat at 16:00 New York (D5) |
| `orb_breakout_ny_mid1r_5m`, `…_mid1p5r_5m` | 5m | same | stop at the range midpoint, 1R / 1.5R, flat at 16:00 (D5 variants) |
| `orb_breakout_ny_mideod_5m` | 5m | same | stop at the range midpoint, no target, closed at 16:00 (D5 variant) |
| `orb_breakout_london_5m` | 5m | XAUUSD, EURUSD, GBPUSD, NAS100, US30, US500 | 08:00-08:15 London range, levels to 16:30, flat at 16:30 London; range stop, 2R (D11) |
| `smc_sniper_min3_15m`, `smc_sniper_min3_5m` | 15m, 5m | the 14 instruments of D1 | Min Score 3, the script's default |
| `smc_sniper_min4_15m`, `smc_sniper_min4_5m` | 15m, 5m | same | Min Score 4 (D11) |

## Decisions applied

The user did not answer doc 13 §13.6, so every default applies.

| Decision | S2 `orb_breakout` | S3 `smc_sniper` |
|---|---|---|
| D3 next-open fills | levels from the signal close; entry skipped when the fill bar opens at or beyond the stop or target | same; a signal whose stop is not beyond the signal close (the script's stale-swing case) is not traded: a persisted `NO_TRADE` `STOP_WRONG_SIDE` with the script's metadata |
| D4 new signal in a trade | ignored; the day's long/short is still used up whenever the script would draw its marker. With either stop the opposite breakout can only come after the stop was hit, so the policy never changes a trade in the book | ignored (the script re-signals on the same swing because levels are never consumed) |
| D5 exits | stop at the other side of the range, 2R from the signal close, flat at 16:00 New York with exit reason `SESSION_CLOSE` (decided on the bar closing at 16:00, filled at the 16:00 open), no entry whose fill would land at or after 16:00 (`NO_TRADE` `FILL_AT_OR_AFTER_FLATTEN`); midpoint 1R / 1.5R / close-only variants | the script's bracket |
| D6 holding | flat every day by the flatten time | held as the script does, through sessions and weekends, until stop or target |
| D10 / D11 | 5m, 15-minute range, NY index set; London ORB | 15m plus 5m, all 14 instruments; Min Score 3 and 4 |
| D13 | script defaults (EMA filter on, 9/20, sessions without a day mask) | script defaults (swings 40/40, OB 10/10 max 3, FVG max 4, ATR 14) |

## What is verified, and what is not

| Check | Where |
|---|---|
| Golden scenarios from hand-built bars: the range by bar open time, the state trigger, the EMA filter blocking without using up the day's signal, the counters, the stale-range carry-over and the gap that is not a new start, the flatten and the late-signal skip, the gap guard, both stop modes; the New York and London windows across the 2026 US and UK clock changes | `tests/unit/strategies/orb_breakout/` |
| Golden scenarios for the sniper: each score point blocking and passing, Min Score 4, the order block and its FIFO cap, the cross evaluated before the swing update (no phantom BOS), levels never consumed, the stop's swing and bar fallbacks, wrong-side stops, na ATR, the gap guard, a signal ignored in a trade, the short mirror; the zone rules unit by unit | `tests/unit/strategies/smc_sniper/` |
| An independent transcription of each script's lines, run against the port on long synthetic series (several seeds, instruments and inputs): identical signals and levels; no ORB trade outlives its flatten time | `…/test_reference.py` |
| Every instance of each `instances.d` file loads, resolves against the real catalog and runs side by side in the lab on synthetic data without a fault | `…/test_instances.py` |
| The signals and their metadata (nested points and zones, nulls for na), the `SESSION_CLOSE` exits and the closed trades are stored in PostgreSQL exactly as computed; the accounts audit clean | `tests/integration/strategies/test_pine_ports_s2_s3_postgres.py` |

**Not verified:** parity with TradingView (doc 13 §13.4 step 2). TradingView
and the market-data APIs are not reachable from the development environment
and no chart exports were provided, so no signal of these ports has been
compared with a chart and none has run on live bars yet. Every point listed
as unverified in [doc 14 §14.6](14-indicators.md#146-evidence-and-what-is-still-unverified)
applies, notably the pivot tie rule and the cross semantics script 5 depends on.

## Warm-up

`warmup_bars` is 300 for S2 (EMA20 and the latest opening range on 5m) and
1000 for S3 (EMA200, the Wilder RSI/ATR, the 81-bar swing windows and the
zone lists). The forward runtime's default `forward.warmup_days: 10` covers S2
and the 5m sniper instances, not 1000 bars of 15m (about 15 calendar days on
markets that close at weekends): those instances log `paper.warmup_short` and
start on a less converged EMA200 and fewer known swings, as the S1 and S8
15m instances do; `forward.warmup_days: 16` in `lab.yaml` would cover them.

## Sizing

S3's stops sit beyond the latest 40/40 swing and can be wide; at 0.5 % risk on
50K, entries that cannot be sized are rejected by the account and recorded
(doc 13 §13.8). Each signal's `metadata.risk_distance` shows the distance.

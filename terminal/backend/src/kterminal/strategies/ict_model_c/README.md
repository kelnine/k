# ict_model_c — ICT Sweep Models C (S9): PD-array bias + IFVG / CISD

Port of Model C of `terminal/pine/received/02_ict_sweep_order_flow_models.pine`
("ICT Sweep + Order Flow Models [NY]"), spec
`terminal/pine/specs/02_ict_sweep_order_flow_models.md`, doc 13 strategy **S9**
(`ict_model_c`). The script is an indicator that tracks its own trades (W/L
table) but places no orders; for Model C it defines entry, stop and target.
Models A and B (`ict_sweep_models`) and D (`ict_model_d`) of the same script are
separate strategies; nothing is shared with them (the fair value gap and zone
helpers are duplicated on purpose). Line numbers below are the received
file's.

| Module | Holds |
|---|---|
| `bias.py` | `PdBias`: `f_pdBias(cLiqLen)` — the persistent 1H PD-array bias, the stored 1H FVGs and the untaken 1H pivots (draw on liquidity) |
| `zones.py` | `HtfFvgFeed` (`f_htfFvg` through the lagged 5m view, `cFresh`), `Zone` and `ZoneBook` (`f_addZone`, `f_updateZones`) |
| `triggers.py` | `ChartGaps` (the 1m gaps), `RunOpens` (the CISD run opens) and `InversionGaps` (the 1m gaps waiting to be inverted) |
| `strategy.py` | `IctModelC`: the window, the trigger scan, and its result turned into signals |

## Rules

The window is New York time (`TZ`, DST-correct) on **all seven days**
(`ALL_DAYS`, L26-27); a bar belongs to it by its **open** time; the window
starts on the first bar inside after a bar outside (`inC and not inC[1]`,
L654). Everything runs on closed 1m bars, in the script's order.

| Rule | Pine | Port |
|---|---|---|
| **Bias** | L228-263, L617, L622: `request.security(cBiasTF, f_pdBias(cLiqLen), lookahead_on)` returns `bias[1]`. Each 1h bar visits the stored 1H FVGs newest first: a bullish FVG closed below its bottom is a bearish event and is removed, else a wick to its top with a close ≥ its midpoint is a bullish event; bearish FVGs mirror it. Only bullish events → +1, only bearish → −1, otherwise unchanged. `var int bias = 0`: no trade until the first reaction | `PdBias.update` on every bar of `ctx.series("1h", tradingview_lag=True)`: a 1m bar inside 1h bar *k* reads the state after bar *k − 1* (doc 05 §5.2.1); the bias starts at 0 on the instance's first bar |
| 1H FVGs | L264-275: `low > high[2]` (top `low`, bottom `high[2]`) / `high < low[2]`, no size filter, at most 10 per side, stored **after** the event checks (never tested on their own bar) | Same, oldest dropped |
| **Draw on liquidity** | L276-297: confirmed `ta.pivothigh/low(cLiqLen, cLiqLen)` (50 kept); every level a later 1h high exceeds (`high > level`, strictly) or low undercuts is removed; `cBSL = liqH.min()` (the lowest untaken high), `cSSL = liqL.max()`, as of the previous 1h bar | `PdBias.bsl` / `.ssl` (`PivotHigh`/`PivotLow`: ≥ on the left, strictly beyond on the right) |
| **Zones** | L301-304, L618, L623, L801-805: `f_htfFvg()` on `cFvgTF` (5m) via `lookahead_on`: the gap of HTF bars *k − 3 … k − 1* (`low[1] > high[3]` → bullish zone `low[1]`-`high[3]`; bearish mirrors), added on the first 1m bar inside HTF bar *k* (`cFresh`), no size or displacement filter | `HtfFvgFeed` on `ctx.series("5m", tradingview_lag=True)`; only the newest visible 5m bar counts, as in Pine |
| Zone cap | L358-368: at most **6** zones, bullish and bearish together, the oldest dropped | `ZoneBook.add` |
| Zone tracking | L372-401, L806: on **every** 1m bar, around the clock: a close beyond the far edge (`close < bot` for a bullish zone) removes the zone; else a bar reaching into it (`low <= top`) marks the first tap (`tapBar`), and a new most extreme price inside (`low < ext`) moves `ext/extBar` and snapshots the CISD level | `ZoneBook.update`, newest zone first; pre-09:30 taps and extremes count (doc 13 §13.7) |
| CISD level | L740-743: `bearRunOpen` = the open of the first candle of the latest run of down-close candles (`close < open and not (close[1] < open[1])`), `bullRunOpen` mirrors it; updated before the zones, so the bar making a new extreme can start the run | `RunOpens` |
| 1m gaps | L163-168: `bullGap = low > high[2] and low − high[2] >= minFvgTicks × mintick` (bottom `high[2]`), `bearGap` mirrors it (top `low[2]`); no displacement filter | `ChartGaps` |
| IFVG list | L745-773: each stored bearish gap (newest first) expires when `bar_index − middle bar > cLook` and is **inverted** (bullish IFVG) by a close above its top, then removed; `invBullBar` = the newest inverted middle candle. Bullish gaps mirror it. The bar's own gap is stored after the checks | `InversionGaps` |
| Window start | L807-810: `cTaken := 0`; the previous C trade is closed "neutral" (no W/L) | `ctx.flatten()` with reason `SESSION_CLOSE` (metadata `trigger` `closed`, `pine_signal` `closeTrade(0)`), filled at the next open, sent whenever a trade filled since the last time exit (below) |
| **Trigger** | L811-830: inside `cWin` (09:30-12:00), `not tC.live`, `cTaken < 1` and `cBiasNow != 0`, the zones newest first: the first with `dir == bias`, tapped, unused and `bar_index − extBar <= cLook` (30) triggers on **IFVG** (`invBull and invBullBar >= tapBar − cLook`; any inverted 1m gap, not necessarily inside the zone) or **CISD** (`close > z.cisd`: a level test, not a cross, so the first 09:30 bar can trigger), with `risk = |close − sl| > 0` | `IctModelC._trigger`, same order and comparisons (`gt`/`ge`: 1e-10 tolerance, false with na); `c_trig` switches either trigger off |
| Stop | L819: `z.ext − slBuf` (long) / `z.ext + slBuf` (short): the extreme inside the zone, the signal bar included | Same |
| Target | L822-825: `cTgt = "Draw on liquidity"`: `cBSL` (long) / `cSSL` (short) when it is beyond the close by > 0 and ≥ `minRR` × risk; otherwise, or when na or already passed, `close ± cRR × risk` (`Fixed RR` always) | Same, from the signal close |
| Entry | L826-829: MARKET at the signal bar's **close**; the zone is marked used, `cTaken += 1` | A MARKET entry at the next open with the script's stop and target (D3, below); metadata `trigger` `C long` / `C short` (the alertcondition titles), `pine_signal` `evC`, `trade_tag` `C IFVG` / `C CISD` |
| Trade exits | L452-464: stop first, then target, from the bar after the entry; the trade is **not** closed at 12:00 | The book's / account's bracket; held to the next window start (D6 main) or flattened at the window end (`after_window: flat`) |

Entry metadata: `via_ifvg`, `via_cisd`, `c_trig`, `bias`, `bias_tf`,
`bias_set_by_bar` (the 1h bar whose events last set the bias),
`bias_events` (its bullish/bearish event counts), `bias_from_bar` (the newest
1h bar fed), `zone` (`dir`, `tf`, `top`, `bottom`, `first_candle`, `added`,
`added_bar_index`, `tap_bar_index`, `extreme`, `extreme_bar_index`,
`cisd_level`), `inverted_gap_bar_index` and `inverted_gap_levels`,
`draw_on_liquidity`, `dol_pivot_time`, `dol_ok`, `target_kind` (`Draw on
liquidity` or `Fixed RR`), the unrounded `script_entry/stop/target`,
`risk_points`, `planned_rr`, `zones_live`, `c_taken`, `window`,
`after_window`, `bar_index`.

## Params

| Param | Pine input | Default |
|---|---|---|
| `c_bias_tf` | `cBiasTF` | `1h` (Pine `60`; `15m`, `30m`, `4h`) |
| `c_fvg_tf` | `cFvgTF` | `5m` (Pine `5`; `15m`) |
| `c_win` | `cWin` | `0930-1200` |
| `c_trig` | `cTrig` | `IFVG or CISD` (`IFVG only`, `CISD only`) |
| `c_look` (≥ 5) | `cLook` | 30 |
| `c_liq_len` (1-10) | `cLiqLen` | 3 |
| `c_tgt` | `cTgt` | `Draw on liquidity` (`Fixed RR`) |
| `c_rr` (≥ 0.5) | `cRR` | 2.0 |
| `min_rr` (≥ 0) | `minRR` | 1.0 |
| `min_fvg_ticks` (≥ 0) | `minFvgTicks` | 0 |
| `sl_buf_ticks` (≥ 0) | `slBufTicks` | 0 |
| `after_window` | — (doc 13 D6) | `hold` (`flat`) |

`c_win` is a Pine session string (`SessionString`, normalised to all days, as
the script appends `ALL_DAYS`). The bias and setup timeframes must be among
the instance's `context_timeframes` (the strategy faults on start otherwise).
`useC` is implied by the strategy; the display inputs (L86-99) do not change
signals. The caps (10 1H FVGs per side, 50 levels, 6 zones) and the New York
time zone are constants in the script and here.

## Variants and instances (`config/instances.d/ict_model_c.yaml`)

| Instance | After the entry |
|---|---|
| `ict_model_c_main_1m` | held until stop, target or the next 09:30 (D6, as the script) |
| `ict_model_c_flat_1m` | closed at the 12:00 window end (D6 variant) |

Both trade all 14 instruments (D10: script 2 on 1m) with `context_timeframes:
[5m, 1h]`, script defaults (D13), one Paper 50K account each with
`max_open_positions: 14` (one position per instrument). D4:
`on_opposite_signal: ignore` — one trade a day, never two at once. The
`IFVG only` / `CISD only` triggers, the 15m setup FVG and the Fixed RR target
are implemented but not instantiated (D11: after the parity check).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| The entry is a MARKET order filled at the next bar's open, with the stop and target the script computed from the signal close; it is skipped when that open is at or beyond the stop or the target (`skip_entry_beyond_levels`, the book reports `ORDER_CANCELLED` `OPEN_BEYOND_STOP` / `OPEN_BEYOND_TARGET`) | Doc 13 D3: the lab cannot fill at a bar's close |
| An entry whose stop or target is not beyond the entry after tick rounding is not traded (persisted `NO_TRADE` `STOP_WRONG_SIDE` / `TARGET_WRONG_SIDE` / `LEVELS_NA` / `LEVELS_NOT_POSITIVE`). The script's state still counts it (`cTaken`, zone used) | Doc 13 D3 (wrong-side stop skip); the script would have traded, so its one-a-day rule is used up |
| Levels are rounded to the tick on the signal | Lab orders are on the tick grid; `script_*` metadata keeps the script's values |
| Time exits — the next window start and the D6 variant's window end — are `ctx.flatten()`, sent whenever a trade filled since the last time exit, whatever `ctx.position` says: they close the trade wherever it is still open (book, account or both) and change nothing where it already closed (when both are flat the signal is recorded `IGNORED` with the book's reason `NOTHING_TO_FLATTEN`) | A position the account kept after the book closed it must not stay open past the script's exit (doc 13 P7/P8) |
| The neutral close at the next window start is a real exit at the next bar's open, with P&L; a new entry on that bar is a replace (flatten, then the entry, both at that open) | The script closes without a price and leaves it out of W/L (L425-427, L606) |
| The script's own trade (`tC`) is not tracked: the trigger needs `not tC.live` **and** `cTaken < 1`, and `cTaken` only resets at the window start, where the script closes `tC` anyway, so `cTaken < 1` alone decides | Equivalent on every bar; a data gap that skips a window start leaves `cTaken` unreset in both |
| `after_window: flat` flattens on the window's last bar (at the 12:00 open), or on the first bar after the window if its last bar is missing; an entry signalled on the window's last bar is a persisted `NO_TRADE` `ENTRY_ON_LAST_WINDOW_BAR` (it would fill at the open the flatten closes it at) | Doc 13 D6 variant; the script never closes at the window end |

## Parity notes

* **Entry price.** The script records the entry at the signal close; the lab
  fills at the next open (plus half the spread) with the script's stop and
  target, so the realised R differs from `planned_rr`, and a next open at or
  beyond the stop or the target skips the trade (D3).
* **Fills on bid/ask.** The script checks its stop and target on the mid-price
  touch; the theoretical book and the paper accounts both resolve on the
  account's bid/ask on the same 1m bars (doc 13 P8). A target the mid touches
  by less than half the spread closes the script's trade but not the lab's,
  which runs to its stop or target or to the next window start.
* **Bias history.** `var int bias = 0` and the stored 1H FVGs (10 per side)
  and pivots (50) build up over whatever history is loaded: on TradingView the
  chart's, in the lab the warm-up's. Until the stored lists have turned over,
  the two can differ; compare only after the same warm-up.
* **Higher-timeframe bars** come from the lab's aggregator (UTC-aligned 5m
  and 1h bars, the same grid as TradingView for every instrument here, whose
  sessions start on the hour). With `tradingview_lag=True` a 5m gap completed
  by the 09:10 bar becomes a zone on the 09:15 1m bar and a 1h bar's bias
  from the next hour's first 1m bar, as on TradingView. A `c_bias_tf: 4h`
  instance would use UTC-aligned 4h bars, not TradingView's session-anchored
  ones (doc 13 P5, open).
* **Bar counts.** `cLook` (the extreme's age and the IFVG window) counts 1m
  bars: thin crypto minutes (ZEC, PUMP, NEAR, HYPE) with missing bars differ
  from minute-based logic, exactly as on a TradingView chart with the same
  gaps. A data gap across 09:30 can skip a window start, exactly like the
  script (`inC[1]` is the previous bar).
* **Not checked against TradingView**: TradingView and the market-data APIs
  are not reachable from the development environment and no chart exports
  were provided. Correctness is shown by golden scenarios on hand-built New
  York tapes (winter, summer, the first EDT Monday, a Sunday for crypto) and
  by an independent procedural transcription of the Pine lines compared with
  the port on 12-day synthetic runs across the November clock change
  (`tests/unit/strategies/ict_model_c`).

## Warm-up

`meta.warmup_bars = 168` **1h** bars (the instance's largest timeframe), i.e.
10,140 1m bars, a week round the clock, for the persistent bias, the 1H FVG
lists and the untaken pivots. It fits `forward.warmup_days` (16 in
`lab.yaml`). The first trade needs a bias (a 1H PD-array reaction after the
first bars), a 5m zone of that side tapped within 30 bars and a trigger in
09:30-12:00. Signals during warm-up are discarded; the one-a-day count and
the zones' `used` flags carry over into the live start as the script's state.

## Licence

The script carries no licence statement (doc 13 §13.8: private use).

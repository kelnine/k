# ict_sweep_models — ICT Sweep Models A (S5) and B (S4)

Port of models A and B of
`terminal/pine/received/02_ict_sweep_order_flow_models.pine` ("ICT Sweep + Order
Flow Models [NY]"), spec `terminal/pine/specs/02_ict_sweep_order_flow_models.md`,
doc 13 strategies **S4** (`ict_model_b`) and **S5** (`ict_model_a`). The script is
an indicator that tracks its own trades (W/L table) but places no orders; it
defines entry, stop and target for both models. Models C and D of the same
script are separate strategies, not part of this package. Line numbers below
are the received file's.

| Module | Holds |
|---|---|
| `engine.py` | The shared 1m series (`SharedSeries`: SMA20 body, displacement FVGs, MSS pivots) and `SweepModel.run`, the state machine both models use |
| `levels.py` | `LiquiditySwings` (Model A's `f_liqSwings`) and `RangeCandle` (Model B's 08:00 range) |
| `strategy.py` | `IctModelA` / `IctModelB`: levels, windows, and the engine's transitions turned into signals |

Both strategies share this folder, so a code change here is a new version of
both.

## Rules

All windows are New York time (`TZ`, DST-correct) on **all seven days**
(`ALL_DAYS`, L26-27); a bar belongs to a window by its **open** time; the
window starts on the first bar inside after a bar outside (`inX and not
inX[1]`, L652-653). Everything runs on closed 1m bars.

| Rule | Pine | Port |
|---|---|---|
| Shared series | L155-170: `body = abs(close − open)`, `avgBody = ta.sma(body, 20)`; `bullGap = low > high[2] and low − high[2] >= minFvgTicks × mintick`; `bullDisp = bullGap and close[1] > open[1] and body[1] >= dispMult × nz(avgBody[1])` (bear mirrors) | `SharedSeries.update`, every bar, Pine comparisons (`gt`/`ge`: 1e-10 tolerance, false with na). `nz(avgBody[1])` is 0 for the first 20 bars |
| MSS pivots | L172-173, L726-737: `ta.pivothigh/pivotlow(mssLen, mssLen)`, stored at their pivot bar `bar_index − mssLen`, newest 100 kept | `PivotHigh`/`PivotLow` (≥ on the left, strictly beyond on the right), `deque(maxlen=100)` |
| `f_pivotBefore` | L184-194: the most recently stored pivot whose bar is before `extBar` | `SharedSeries.pivot_before` |
| **A levels** | L197-222, L616: `request.security("15", f_liqSwings(aSwing), lookahead_on)`; every 15m bar pushes a confirmed `ta.pivothigh/low(2, 2)` (50 kept) and removes every level its high exceeds (`high > level`, low mirrors); the value is `[lastH[1], lastL[1]]`, the most recent survivor as of the **previous** 15m bar | `LiquiditySwings` fed with the bars of `ctx.series("15m", tradingview_lag=True)`: a 1m bar inside 15m bar *k* sees the state after bar *k − 1* (doc 05 §5.2.1). No freshness check: a level can be days old |
| **A window** | `aWin` 2000-0200 (L46, L646), `needBack = false` (L783) | `a_win` |
| **B range** | L786-794: high/low of the 1m bars opening in `bRange` 0800-0900, reset on its first bar; L796 `bFresh = time − bT0 < 86400000` | `RangeCandle`; a range whose first bar opened 24 h or more before the window start is na |
| **B window** | `bWin` 0900-1200 (L52, L653), `needBack = true` (L797) | `b_win` |
| Window start | L470-483: levels `hi/lo` set; idle (state 4) when either is na or `hi <= lo`; direction, MSS, back-in flag and FVG cleared | `SweepModel.run(start_now=True)` |
| Window end | L491-492: outside the window every unfilled stage (states 0-2) is dropped | Same; the resting order is cancelled (below) |
| Sweep | L515-538 (states 0-1): `high > hi` starts a short setup, `low < lo` a long one; while unarmed a new extreme beyond `ext` moves `ext/extBar` and clears MSS, back-in and FVG; sweeping the other level flips the direction; the low test runs second, so an outside bar ends long. No close back inside is needed for the sweep | `SweepModel.run`, same order |
| Back inside (B) | L542-543 / L569-570: a close above `lo` (long) / below `hi` (short), on any bar after the latest extreme | `back_in` |
| Displacement FVG | L544-550 / L571-577: `bullDisp`, its first candle at or after `extBar` (`bar_index − 2 >= extBar`) and, once the MSS happened, its middle candle `<= mssBar + 3`; the newest one wins; dropped when a close goes beyond its far edge | Same |
| MSS | L551-558 / L578-585: a close beyond the `f_pivotBefore(extBar)` pivot | Same |
| Arming | L559-567 / L586-594: MSS, a live FVG with `fvgBar <= mssBar + 3`, and (B) back inside → limit at `fvgTop` (long) / `fvgBot` (short), or the FVG's 50% (`FVG 50% (CE)`); stop `ext ∓ slBuf`; target the opposite level when it is beyond the entry by ≥ `minRR` × risk, else `entry ± RR × risk` | A **LIMIT** entry with these levels at the arming bar's close (metadata `trigger` `A long setup` / `B short setup`, the script's alertcondition titles; `pine_signal` `evA`/`evB`) |
| Fill | L496-510: from the next bar, `low <= entry` fills at `min(open, entry)` (short mirrors); a stop touched on the fill bar is a loss | The book and the paper accounts fill resting limits the same way (the accounts on bid/ask) |
| Missed | L502, L511-512: the target traded before the fill → state 4 | `EXIT_*` of the resting order on that bar (metadata `trigger` `A missed` / `B missed`) |
| One cycle per window | After a fill or a miss the model idles until its next window start (L489-490) | Same (state 3 is kept until the next start; the script's 3 → 4 changes nothing it reads) |
| Trade exits | L452-464: stop first, then target, from the bar after the fill; L470-472: a trade still open at the model's **next window start** is closed "neutral" (no W/L) | The book's / account's bracket; at the next window start an `EXIT_*` with reason `SESSION_CLOSE` (metadata `trigger` `closed`, `pine_signal` `closeTrade(0)`), filled at the next open |

Entry metadata: the window's levels (`range_high`, `range_low`; A:
`level_high_pivot_time`, `level_low_pivot_time`, `levels_from_15m_bar`; B:
`range_start`, `range_bars`, `range_fresh`), `swept`, `sweep_extreme`,
`sweep_bar_index`, `back_in`, `mss_level`, `mss_pivot_bar_index`,
`mss_bar_index`, `fvg_top`, `fvg_bottom`, `fvg_bar_index`,
`displacement_body`, `avg_body`, `entry_mode`, `target_kind` (`Opposite level`
or `Fixed RR`), the unrounded `script_entry/stop/target`, `planned_rr`,
`expires_after_bars`, `state`, `window`, `after_window`, `bar_index`.

## Params

| Param | Pine input | Default |
|---|---|---|
| `entry_mode` | `entryMode` | `FVG edge` (`FVG 50% (CE)`) |
| `mss_len` (1-10) | `mssLen` | 2 |
| `disp_mult` (≥ 0.5) | `dispMult` | 1.5 |
| `min_fvg_ticks` (≥ 0) | `minFvgTicks` | 0 |
| `sl_buf_ticks` (≥ 0) | `slBufTicks` | 0 |
| `min_rr` (≥ 0) | `minRR` | 1.0 |
| `a_swing` (1-10), `a_win`, `a_tgt`, `a_rr` (≥ 0.5) | `aSwing`, `aWin`, `aTgt`, `aRR` | 2, `2000-0200`, `Opposite level`, 2.0 |
| `b_range`, `b_win`, `b_tgt`, `b_rr` (≥ 0.5) | `bRange`, `bWin`, `bTgt`, `bRR` | `0800-0900`, `0900-1200`, `Opposite level`, 2.0 |
| `after_window` | — (doc 13 D6) | `hold` (`flat`) |

Session params are Pine session strings (`SessionString`, normalised to all
days, as the script appends `ALL_DAYS`). `useA`/`useB` are implied by the
strategy chosen; the display inputs (L86-99) do not change signals. The
24-hour freshness rule, the caps (100 pivots, 50 levels) and the New York time
zone are constants in the script and here.

## Variants and instances (`config/instances.d/ict_model_a.yaml`, `ict_model_b.yaml`)

| Instance | Model | After the window |
|---|---|---|
| `ict_model_a_main_1m` | A, 1m (15m context) | held until stop, target or the next 20:00 (D6, as the script) |
| `ict_model_a_flat_1m` | A, 1m | closed at the 02:00 window end (D6 variant) |
| `ict_model_b_main_1m` | B, 1m | held until stop, target or the next 09:00 (D6, as the script) |
| `ict_model_b_flat_1m` | B, 1m | closed at the 12:00 window end (D6 variant) |

All 14 instruments (D10: script 2 on 1m), script defaults (D13), one Paper 50K
account per instance with `max_open_positions: 14` (one position per
instrument). D4: `on_opposite_signal: ignore` — the state machine never has
more than one setup or trade. The CE entry and Fixed RR variants are
implemented but not instantiated (D11: after the parity check).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| The script's cancels become `EXIT_*` signals of the resting order: "missed" on the bar the target trades, and the window end; the order also carries `expires_after_bars` = the bars left in the window, so book and accounts drop it after the window's last bar without a signal | The lab has no such rules. The expiry is the script's "last fill check on the last in-window bar" (L491-496), and keeps the accounts (which fill on bid/ask and may still be waiting when the book has filled) from holding an order past the window |
| A setup armed on the window's last bar places no order (persisted `NO_TRADE` `ARMED_ON_LAST_WINDOW_BAR`) | The script cancels it on the next bar before any fill check |
| A setup whose stop or target is not beyond the entry after tick rounding is not traded (persisted `NO_TRADE` `STOP_WRONG_SIDE` / `TARGET_WRONG_SIDE` / `LEVELS_NA` / `LEVELS_NOT_POSITIVE`); the script's state machine continues as if it were placed | Doc 13 D3; possible only with the CE entry (a half-tick 50% level) |
| Levels are rounded to the tick on the signal (the script uses the unrounded CE level and `entry ± RR × risk`) | Lab orders are on the tick grid; `script_*` metadata keeps the script's values |
| Missing bars: when the window's last bars are missing, the expiry (counted in bars) outlives the window, so the strategy cancels on the first bar after it; if the book fills the order on that bar, the position is closed at the next open (`SESSION_CLOSE`, `trigger` `late fill`). If the script fills where the book did not (only possible after rounding a CE level), the order is cancelled (`fill not matched`) | Keeps the book on the script's state machine |
| The neutral close at the next window start is a real exit at the next bar's open, with P&L | The script closes without a price and leaves it out of W/L (L425-427, L606) |
| `after_window: flat` closes a filled trade on the window's last bar (at the next open), or on the first bar after the window if its last bar is missing | Doc 13 D6 variant; the script never closes at the window end |
| D3's gap guard (skip a market entry when the next open is beyond its levels) does not apply: models A and B enter with resting limits, which fill at the open when a bar opens through them, as in the script (L504) | D3 covers signals priced at the bar close (models C and D); a limit filled at an open beyond the stop is stopped on the fill bar, as the script's `stoppedNow` |

## Parity notes

* **Fills on bid/ask.** The script fills, stops and targets on the mid-price
  touch. The theoretical book does too (so the strategy's state agrees with
  it), but the paper accounts trigger limits, stops and targets on bid/ask:
  a limit the mid just touches fills in the script and the book but not in
  the account. The account then still holds the order until the window's
  last bar (expiry) and may fill later; a target the mid touches by less than
  half the spread closes the book's trade but not the account's, which then
  runs to its own stop or target (the strategy's time exits only reach
  positions the book holds; doc 13 P8 would resolve the book at bid/ask).
* **Fill bar.** The script never takes profit on the fill bar (L453); the book
  and accounts do when the bar closes beyond the target, and a bar that opens
  beyond the target counts as a target before the stop. Both are rare on 1m.
* **15m bars** come from the lab's aggregator (UTC-aligned quarters, the same
  grid as TradingView for every instrument here). With
  `tradingview_lag=True` a swing confirmed by the 19:45 bar is visible from
  the 20:00 bar, as on TradingView; a window starting inside a quarter
  (e.g. `1959-…`) would not see it yet.
* **History start.** A's levels are the survivors of up to 50 swings and can
  be days old; TradingView's depend on how much 15m history the chart loaded.
  Compare levels only after the same warm-up.
* **Bar counts.** `mssBar + 3`, `bar_index − 2 >= extBar` and the 1m pivots
  count bars: thin crypto minutes (ZEC, PUMP, NEAR, HYPE) with missing bars
  differ from a gap-free chart. A data gap across a window boundary can skip a
  window start, exactly like the script (`inX[1]` is the previous bar).
* **Not checked against TradingView**: TradingView and the market-data APIs
  are not reachable from the development environment and no chart exports
  were provided. Correctness is shown by golden scenarios on hand-built New
  York tapes (winter, summer, the first EDT Monday, the November fall-back
  night) and by an independent transcription of the Pine lines compared on
  long synthetic runs (`tests/unit/strategies/ict_sweep_models`,
  `…/ict_model_a`, `…/ict_model_b`).

## Warm-up

Model A: `meta.warmup_bars = 480` **15m** bars (the instance's largest
timeframe), i.e. 7,215 1m bars, five days round the clock, for the 15m
swing lists; Model B: 2,880 1m bars (two days) for the 08:00 range, the
pivots and SMA20(body). Both fit the default `forward.warmup_days: 10`
(about 7.3 calendar days for A on markets that close at weekends). Signals
during warm-up are discarded: a setup armed then is not traded, and when it
ends after the live start the strategy sends one cancel that finds no order
(the account records `NO_MATCHING_POSITION`).

## Licence

The script carries no licence statement (doc 13 §13.8: private use).

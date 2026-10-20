# ict_model_d — ICT Sweep Models D (S11): order-flow absorption

Port of Model D of `terminal/pine/received/02_ict_sweep_order_flow_models.pine`
("ICT Sweep + Order Flow Models [NY]"), spec
`terminal/pine/specs/02_ict_sweep_order_flow_models.md`, doc 13 strategy **S11**
(`ict_model_d`). The script is an indicator that tracks its own trades (W/L
table) but places no orders; for Model D it defines entry, stop and target.
Models A and B (`ict_sweep_models`) and C (`ict_model_c`) of the same script are
separate strategies; nothing is shared with them (the fair value gap and zone
helpers are duplicated on purpose). Line numbers below are the received
file's.

The "order flow" is a **proxy**: the script's default delta source, `Candle
estimate`, splits each 1m bar's volume by where it closed in its range. It is
not real bid/ask volume, and on a feed with tick volume (FX, CFDs) or none it
is a different strategy or none at all (doc 13 D9).

| Module | Holds |
|---|---|
| `flow.py` | `CandleFlow` (the candle-estimate delta, `avgVol`, the aggressive flags) and `ScriptTrade` (the script's own D trade: `openTrade`, `closeTrade`, `manage`) |
| `profile.py` | `value_area` (`f_valueArea`) and `OvernightProfile` (the 18:00-09:30 store, the value area and the overnight high/low) |
| `zones.py` | `HtfFvgFeed` (`f_htfFvg` through the lagged 15m view, `dFresh`), `Zone` and `ZoneBook` (`f_addZone`, the kill rule of `f_updateZones`, `f_zoneTouch`) |
| `strategy.py` | `IctModelD`: the key levels, the window, the candidates and triggers, and the signals |

## Rules

The windows are New York time (`TZ`, DST-correct) on **all seven days**
(`ALL_DAYS`, L26-27); a bar belongs to a window by its **open** time; a window
starts on the first bar inside after a bar outside (`inD and not inD[1]`,
L655). Everything runs on closed 1m bars, in the script's order.

| Rule | Pine | Port |
|---|---|---|
| ATR and tolerance | L160-161: `atr = ta.atr(14)` (Wilder, SMA-seeded; na for 13 bars), `tol = dTolAtr × atr` | `Atr(14)` every bar |
| **Delta** | L634-640: `vol = nz(volume)`; `buyV = vol × (close − low) / (high − low)`, half the volume each when the range is 0; `sellV = vol − buyV`; `barDelta = buyV − sellV`, `barVol = buyV + sellV` | `CandleFlow.update` |
| **Aggressive bars** | L641-643: `avgVol = ta.sma(barVol, 20)` (the current bar included; na for 19 bars); `aggrBuy = barVol > 0 and barVol >= dVolMult × avgVol and barDelta >= dDeltaPct % × barVol`, `aggrSell` with `−barDelta` | Same (`gt`/`ge`: 1e-10 tolerance, false with na) |
| Script trade | L434-464, L779: the D trade opened at the signal close; from the next bar a touch of the stop (checked first) or the target closes it. D looks for setups only while it is closed | `ScriptTrade`, managed before anything else on the bar, independent of the lab's fills (below) |
| **Overnight session** | L835-847: `dOnSess` 1800-0930; on its first bar the stored bars are cleared and the high/low restart; every bar inside stores `high`, `low`, `nz(volume)` and extends the high/low | `OvernightProfile.update` |
| **Value area** | L307-339, L848-854: on the first bar after the session (normally 09:30) `dRows` (50) rows over the session's low-high; each bar's volume spread evenly over the rows from its low's row to its high's (`floor((p − lo) / step)`, clamped); POC = the **first** row with the most volume; from the POC the area grows one row at a time towards the larger neighbour, **ties going up**, until it holds `dVaPct` (70) % or covers every row; VAH = the top edge of its highest row, VAL = the bottom edge of its lowest. The session high/low become ONH/ONL. Kept until the next session ends | `value_area`, copied operation for operation (same summation order) |
| PDH / PDL | L620: `request.security("D", [high[1], low[1]], lookahead_on)`: the previous daily bar of the symbol's own session | `ctx.periods.previous("D")` on the instrument's catalog trading day (doc 13 D8: 17:00 New York for CME, 00:00 UTC for crypto), switching on the first bar of a new day |
| **15m zones** | L301-304, L619, L624, L856-861: `f_htfFvg()` on `dFvgTF` (15) via `lookahead_on`: the gap of 15m bars *k − 3 … k − 1* (`low[1] > high[3]` → bullish zone `low[1]`-`high[3]`; bearish mirrors), added on the first 1m bar inside 15m bar *k* (`dFresh`), no size or displacement filter; at most **6** zones bull and bear together, the oldest dropped | `HtfFvgFeed` on `ctx.series("15m", tradingview_lag=True)`, `ZoneBook.add` |
| Zone life and touch | L862-865, L372-381, L403-414: a 1m close beyond the far edge removes the zone; a bar whose range overlaps a bullish zone (`low <= top and high >= bot`) is **at support**, a bearish zone **at resistance** | `ZoneBook.update`, `ZoneBook.touch` (taps, extremes and CISD levels, which D never reads, are not kept) |
| **Key levels** | L866-871: VAH, VAL (`useVA`), ONH, ONL (`useON`), PDH, PDL (`usePD`), `dMan1`, `dMan2` (when > 0): any level with `low <= lvl + tol and high >= lvl − tol` puts the bar at support **and** at resistance | `IctModelD._key_levels`; `dZoneMode` switches zones or levels off (L101-102) |
| Window start | L873-877: both candidates reset; a live D trade is closed "neutral" (no W/L) | `ctx.flatten()` with reason `SESSION_CLOSE` (metadata `trigger` `closed`, `pine_signal` `closeTrade(0)`), filled at the next open, sent whenever a trade filled since the last time exit (below); the script's trade is closed too |
| Outside the window | L878-880: both candidates reset on every bar | Same |
| **Long** | L883-902, inside `dWin` (09:30-16:00) while the script's trade is closed: a live candidate extends its extreme (`min(ext, low)`) and is dropped when a bar closes below its low or `bar_index − dLBar > dMaxBars` (10); else an `aggrBuy` bar closing **above** its body top triggers: stop `ext − slBuf`, `risk = close − sl > 0`, target `close + dRR × risk`; both candidates reset. With no candidate (and still no trade), an `aggrSell` bar at support becomes one: body top `max(open, close)`, its low, extreme = its low. A live candidate is never refreshed | `IctModelD._long_branch`, same order; metadata `trigger` `D long` (the alertcondition title), `pine_signal` `evD`, `trade_tag` `D absorption` |
| **Short** | L904-924, after the long branch and only while still no trade: mirror (an `aggrBuy` bar at resistance; an `aggrSell` bar closing below its body bottom `min(open, close)`; stop `ext + slBuf` at the highest high since) | `IctModelD._short_branch`; `trigger` `D short` |
| Entry | L891, L913: at the signal bar's **close**; no daily cap — sequential trades, one at a time, even on the bar the previous one closes (manage runs first) | A MARKET entry at the next open with the script's stop and target (D3, below) |

Entry metadata: `absorbed` (`sellers` / `buyers`), `candidate` (`bar_index`,
`time`, `bars_ago`, `body_edge`, `origin` — its low or high —, `extreme`, its
`volume`, `avg_volume`, `delta`, `delta_pct`, and `at`: the zones and levels
that put it at support / resistance), `trigger_bar` (the same flow numbers),
`atr`, `tolerance`, `levels` (VAH, VAL, ONH, ONL, PDH, PDL, the manual levels
and the POC; null when na or off), `zones_live`, `zone_mode`,
`delta_source`, the unrounded `script_entry/stop/target`, `risk_points`,
`planned_rr`, `window`, `after_window`, `bar_index`.

## Params

| Param | Pine input | Default |
|---|---|---|
| `d_win` | `dWin` | `0930-1600` |
| `d_zone_mode` | `dZoneMode` | `HTF FVG + key levels` (`HTF FVG only`, `Key levels only`) |
| `d_fvg_tf` | `dFvgTF` | `15m` (Pine `15`; `5m`, `30m`, `1h`) |
| `d_delta` | `dDelta` | `Candle estimate` (the only value: `Intrabar (lower TF)` is not ported) |
| `d_vol_mult` (≥ 1) | `dVolMult` | 1.5 |
| `d_delta_pct` (5-100) | `dDeltaPct` | 30 |
| `d_max_bars` (≥ 2) | `dMaxBars` | 10 |
| `d_rr` (≥ 0.5) | `dRR` | 2.0 |
| `d_tol_atr` (≥ 0) | `dTolAtr` | 0.25 |
| `d_on_sess` | `dOnSess` | `1800-0930` |
| `d_va_pct` (50-95) | `dVaPct` | 70 |
| `d_rows` (10-200) | `dRows` | 50 |
| `use_va`, `use_on`, `use_pd` | `useVA`, `useON`, `usePD` | true |
| `d_man1`, `d_man2` | `dMan1`, `dMan2` | 0 (off) |
| `sl_buf_ticks` (≥ 0) | `slBufTicks` | 0 |
| `after_window` | — (doc 13 D6) | `hold` (`flat`) |

Session params are Pine session strings (`SessionString`, normalised to all
days, as the script appends `ALL_DAYS`). With zones on, `d_fvg_tf` must be among
the instance's `context_timeframes` (the strategy faults on start otherwise).
`dLtf` (the intrabar timeframe) only serves the intrabar source and is not a
param. `useD` is implied by the strategy; the display inputs (L86-99) do not
change signals. ATR 14, SMA 20, the zone cap and the New York time zone are
constants in the script and here.

## Variants and instances (`config/instances.d/ict_model_d.yaml`)

| Instance | After the entry |
|---|---|
| `ict_model_d_main_1m` | held until stop, target or the next 09:30 (D6, as the script) |
| `ict_model_d_flat_1m` | closed at the 16:00 window end (D6 variant) |

Both trade **MNQ and the crypto pairs** (BTCUSD, SOLUSD, NEARUSD, ZECUSD,
HYPEUSD, PUMPUSD) on 1m with `context_timeframes: [15m]`: D9 keeps the
volume-driven model off the tick-volume CFDs, metals and FX until a separate,
labelled instance is wanted. Script defaults (D13), one Paper 50K account each
with `max_open_positions: 7` (one position per instrument). D4:
`on_opposite_signal: ignore` — one trade at a time. The `HTF FVG only` / `Key
levels only` modes are implemented but not instantiated (D11: after the
parity check).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| The entry is a MARKET order filled at the next bar's open, with the stop and target the script computed from the signal close; it is skipped when that open is at or beyond the stop or the target (`skip_entry_beyond_levels`, the book reports `ORDER_CANCELLED` `OPEN_BEYOND_STOP` / `OPEN_BEYOND_TARGET`) | Doc 13 D3: the lab cannot fill at a bar's close |
| An entry whose stop or target is not beyond the entry after tick rounding is not traded (persisted `NO_TRADE` `STOP_WRONG_SIDE` / `TARGET_WRONG_SIDE` / `LEVELS_NA` / `LEVELS_NOT_POSITIVE`) | Doc 13 D3 (wrong-side stop skip) |
| The script's own trade (`ScriptTrade`) decides when D looks for the next setup, not the lab's position: a trade the lab skipped (D3) or still holds still blocks, or frees, the model exactly as in the script | D looks for setups only while `tD` is closed (L881, L897, L904, L919); its stop and target are mid-price touches of the unrounded levels |
| When the script opens a new trade while the theoretical book still holds the previous one (its target or stop touched the script's unrounded level but not the book's rounded one, or not at the account's bid/ask), the strategy first sends `ctx.flatten()` (`trigger` `replaced`, exit reason `SIGNAL_EXIT`), then the entry: both at the next open | Doc 13 D4 (one trade at a time) with the replace rule (doc 05 §5.3); keeps the lab on the script's trade sequence |
| Levels are rounded to the tick on the signal | Lab orders are on the tick grid; `script_*` metadata keeps the script's values |
| Time exits — the next window start and the D6 variant's window end — are `ctx.flatten()`, sent whenever a trade filled since the last time exit, whatever `ctx.position` says: they close the trade wherever it is still open (book, account or both) and change nothing where it already closed (when both are flat the signal is recorded `IGNORED` with the book's reason `NOTHING_TO_FLATTEN`) | A position the account kept after the book closed it must not stay open past the script's exit (doc 13 P7/P8) |
| The neutral close at the next window start is a real exit at the next bar's open, with P&L | The script closes without a price and leaves it out of W/L (L425-427, L606) |
| `after_window: flat` flattens on the window's last bar (at the 16:00 open), or on the first bar after the window if its last bar is missing; an entry signalled on the window's last bar is a persisted `NO_TRADE` `ENTRY_ON_LAST_WINDOW_BAR` | Doc 13 D6 variant; the script never closes at the window end |
| `Intrabar (lower TF)` delta (L629-633, `request.security_lower_tf` on seconds data) is not ported; `d_delta` accepts only `Candle estimate` | The terminal has no seconds feed; it cannot be tested or matched to TradingView (spec question 7, default) |
| PDH/PDL come from `ctx.periods` (the instrument's trading day built from the 1m bars) instead of TradingView's daily bars; the first, partial day an instance sees never becomes the previous day (na until warm-up has covered a whole day) | Doc 13 D8; the lab has no daily bars (doc 05 §5.2.2) |

## Parity notes

* **Volume.** Everything depends on the feed's volume: MNQ's from CME (via a
  TradingView export until a CME vendor is chosen, doc 13 D1) and the crypto
  exchanges' own. The same symbol on another exchange has another volume and
  other signals; the synthetic lab volume says nothing about real behaviour.
* **Entry price.** The script records the entry at the signal close; the lab
  fills at the next open (plus half the spread) with the script's stop and
  target, so the realised R differs from `planned_rr` (2), and a next open at
  or beyond the stop or the target skips the trade (D3).
* **Fills on bid/ask.** The script checks its stop and target on the mid-price
  touch; the theoretical book and the paper accounts both resolve on the
  account's bid/ask on the same 1m bars (doc 13 P8). See the replace rule
  above for a trade the script closed and the lab did not.
* **Overnight profile.** Computed from the lab's 1m bars by open time in
  18:00-09:30 New York (16.5 hours on the night the clocks go back, 14.5 when
  they go forward). The instance's first bar counts as a session start when
  it lies inside the session (Pine's `inON[1]` is false on the first bar), so
  the first profile can be partial; the warm-up covers it.
* **15m bars** come from the lab's aggregator (UTC-aligned quarters, the same
  grid as TradingView for every instrument here). With `tradingview_lag=True`
  a gap completed by the 10:30 bar becomes a zone on the 10:45 1m bar, as on
  TradingView.
* **Bar counts.** `dMaxBars` counts 1m bars: thin crypto minutes (ZEC, PUMP,
  NEAR, HYPE) with missing bars differ from minute-based logic, exactly as on
  a TradingView chart with the same gaps. A data gap across 09:30 can skip a
  window start, exactly like the script (`inD[1]` is the previous bar).
* **Not checked against TradingView**: TradingView and the market-data APIs
  are not reachable from the development environment and no chart exports
  (with volume) were provided. Correctness is shown by golden scenarios on
  hand-built New York tapes (winter, summer, the first EDT Monday, a Sunday
  for crypto, the overnight session across both clock changes), hand vectors
  of the value area, and an independent procedural transcription of the Pine
  lines compared with the port on 12-14-day synthetic runs of gold and bitcoin
  across the November clock change (`tests/unit/strategies/ict_model_d`).

## Warm-up

`meta.warmup_bars = 200` **15m** bars (the instance's largest timeframe),
i.e. 3,015 1m bars, about two days round the clock, for ATR(14), the volume
average, the 15m zones and a complete overnight session. Forward sessions also
size the warm-up for the previous trading day (`ctx.periods`,
`period_warmup_bars("D", "1m")` = 3,001 bars). Both fit `forward.warmup_days`
(16 in `lab.yaml`). Signals during warm-up are discarded; the script's own
trade and the candidates carry over into the live start as the script's
state.

## Licence

The script carries no licence statement (doc 13 §13.8: private use).

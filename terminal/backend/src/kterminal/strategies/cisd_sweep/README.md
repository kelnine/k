# cisd_sweep — CISD after a liquidity sweep (S6)

Port of the main-chart CISD model of
`terminal/pine/received/01_breakout_targets_ict_cisd.pine` ("Breakout Targets + ICT
Levels + CISD", BT+ICT), spec `terminal/pine/specs/01_breakout_targets_ict_cisd.md`,
doc 13 strategy **S6**. The script is an indicator: it prints an Entry at the CISD
level, a stop and TP1/TP2 and tracks the trade on the chart, but places no order.
Its range breakout, trendlines, rejection-block zones, opens and session drawings are
display or alert only (doc 13 D12); its MTF scanner is a second, different CISD model
ported as `cisd_scanner` (S10). Line numbers below are the received file's.

| Module | Holds |
|---|---|
| `runs.py` | `CisdRuns`: the latest up-close / down-close runs and the close-through check (L629-672), shared with `cisd_scanner` |
| `levels.py` | `SessionClock` (`inSess`, L390) and `SessionRange` (the session high/low trackers, L477-537) |
| `orders.py` | `CisdTradeStrategy`: doc 13 D7/D4/D3 — how a CISD becomes orders; shared with `cisd_scanner` |
| `strategy.py` | `CisdSweep`: the model (pivots, ATR, sessions, PD/PW/PM, sweeps, CISD, window) |

`cisd_scanner` inherits `CisdTradeStrategy` from this folder, so a code change here is
also a new version of S10 (the registry hashes every strategy base class's folder).

## Rules

Sessions are New York time (`tz`, DST-correct) on every day (the session strings have
no day mask, so Pine's default applies); a bar belongs to a session by its **open**
time (`time(timeframe.period, s, tz)`). Everything runs once per closed bar, in this
order:

| Rule | Pine | Port |
|---|---|---|
| Pivots, ATR | L192-194: `ta.pivothigh(high, pvL, pvR)`, `ta.pivotlow`, `ta.atr(14)`, every bar | `PivotHigh`/`PivotLow` (≥ on the left, strictly beyond on the right), `Atr(14)` |
| Session ranges | L477-537: on the first bar inside (`inX and not inX[1]`) H/L = the bar's; on later bars inside, running max/min; kept after the session | `SessionClock` + `SessionRange` for Asia `2000-0000`, London `0200-0500`, NY AM `0930-1200`; NY PM `1330-1600` only for the window |
| PD/PW/PM levels | L400-402: `request.security(…, "D"/"W"/"M", [high[1], low[1]], lookahead_on)` | `ctx.periods.previous("D"/"W"/"M")` on the catalog's trading day (17:00 New York; UTC midnight for crypto), doc 05 §5.2.2 |
| Latest pivot | L588-593: `lastPH := ph` when a pivot high is confirmed (pvR bars late) | `last_ph` / `last_pl` |
| Session levels | L595-600: `sAH = showSess and not inAsia ? asiaH : na` (likewise London, NY AM): only outside the session, only on charts ≤ 60 minutes (L388) | `SessionRange.levels` |
| Trade-through | L585-586: `tookHigh(l) = not na(l) and high > l and high[1] <= l` (low mirrors) | `gt`/`le` (Pine's 1e-10 tolerance; false with na) |
| Buy-side sweep | L614, L619-621: `high > lastPH` or a trade-through of PDH, PWH, PMH, Asia, London or NY AM high; stamps `lastBslBar` and clears `lastPH`. Levels are never retired | Same; the sweep's bar, time and the levels it took are kept for the metadata |
| Sell-side sweep | L615, L622-624: mirror; stamps `lastSslBar`, clears `lastPL` | Same |
| Runs | L629-652: an up-close bar after a bar that was not one starts a run (open, high); while its open is live the high is extended with every bar, the CISD bar included; a doji ends a run | `CisdRuns.update` |
| Body filter | L631: `abs(close − open) >= minBody × nz(atr)` — `nz` makes it pass every body before ATR(14) exists | `ge(body, min_body × nz(atr))` |
| Bearish CISD | L660-665: a close below the live up-close run's open (after its first bar) **consumes** the level, then signals if the body passes and `bar_index − lastBslBar <= sweepLook` (or `reqSweep` is off) | `CisdRuns.bear_cross` + the filters |
| Bullish CISD | L667-672: checked only if no bearish CISD passed; mirror | Same order. The case it guards cannot occur: a down run opening below a live up run's open closes below that open on its first bar (consuming it), so no close can lie between two live levels |
| Signal window | L674-683: `sigWindow` (Any time, NY AM, NY AM + NY PM, London + NY AM, London + NY AM + NY PM) by the CISD bar's sessions; ignored on charts > 60 minutes; applied **after** the level was consumed | `sig_window` |
| Trade | L730-736: entry = the CISD level, stop = the run's extreme, R = \|entry − stop\|, TP1 = entry ± 1R, TP2 = entry ± 2R (na when the R multiple is 0) | `CisdTradeStrategy._entry` |
| Tracking | L751-765: the trade ends at SL, TP2 (or TP1 without TP2), or 4,500 bars after the signal; any new CISD overwrites it (L721) | below (D7, D4) |

### Orders (doc 13 D7, D4, D3; `orders.py`)

| Situation | Signal |
|---|---|
| CISD, `entry: limit` | `LONG`/`SHORT` **LIMIT** at the CISD level, stop at the run extreme, target TP1 or TP2 (`target`), `expires_after_bars` 12 (`limit_expiry_bars`) |
| The limit is unfilled and TP1 trades on a later bar | `EXIT_*` of the resting order on that bar (`trigger` `order cancelled`, `detail` `TP1 traded before the fill`); a bar that fills the order and trades TP1 keeps the fill (`cancel_on_tp1`) |
| CISD, `entry: market` | `LONG`/`SHORT` MARKET at the next open with the script's absolute stop and target; persisted `NO_TRADE` (`STOP_WRONG_SIDE` / `TARGET_WRONG_SIDE`) when either is not beyond the signal close; the book and the account skip it when the next open is at or beyond either (`OPEN_BEYOND_STOP` / `OPEN_BEYOND_TARGET`, meta `skip_entry_beyond_levels`) |
| New CISD, an order resting | `EXIT_*` of the order (`detail` `replaced by a new CISD`), then the new entry |
| New CISD, a trade open | `EXIT_*` (`trigger` `trade replaced`, reason `replaced by a new CISD`), then the new entry — both fill at the next open (the engine's replace). In market mode an opposite CISD is the entry alone: the engine reverses at the next open (close reason `REVERSAL`) |
| New CISD that cannot be traded (D3) | the old trade is still exited; the CISD is a persisted `NO_TRADE` |
| 4,500 bars after the trade's signal | `EXIT_*` with reason `SESSION_CLOSE` (`trigger` `tracking ended`) |

Entry metadata: `trigger` (`Bullish CISD` / `Bearish CISD`, the script's alert titles),
`pine_signal` (`bullCisd` / `bearCisd`), `model` `main`, `cisd_level`, `run_extreme`,
`run_start_bar_index`, `run_bars`, `body`, `atr` (null while na), `min_body_points`,
`sweep` (`bar_index`, `bars_ago`, `time`, `levels`: each level taken on the sweep bar
with its price — `pivot high`, `PDH`, `PWH`, `PMH`, `Asia high`, `LNDN high`, `NY AM
high` and the lows), `sig_window`, `levels` (every sweep level live on the signal bar,
null where na), the unrounded `script_entry`, `script_stop`, `script_tp1`, `script_tp2`,
`risk_points`, `entry_mode`, `target_leg`, `expires_after_bars`, `cancel_on_tp1`,
`bar_index`.

## Params

| Param | Pine input | Default |
|---|---|---|
| `req_sweep` | `reqSweep` | true |
| `sweep_look` (≥ 1) | `sweepLook` | 12 |
| `min_body` (≥ 0) | `minBody` | 0.3 |
| `tp1_r`, `tp2_r` (≥ 0; 0 = none) | `tp1R`, `tp2R` | 1.0, 2.0 |
| `pv_l`, `pv_r` (≥ 1) | `pvL`, `pvR` | 5, 5 |
| `tz` | `tz` | `America/New_York` |
| `asia_sess`, `lon_sess`, `ny_am_sess`, `ny_pm_sess` | `asiaSess`, `lonSess`, `nyAmSess`, `nyPmSess` | `2000-0000`, `0200-0500`, `0930-1200`, `1330-1600` |
| `sig_window` | `sigWindow` | `Any time` |
| `entry` | — (D7) | `limit` (`market`) |
| `target` | — (D7) | `tp2` (`tp1`) |
| `limit_expiry_bars` (≥ 1) | — (D7) | 12 |
| `cancel_on_tp1` | — (D7) | true |

`showCisd` and `showTrade` are always on (off removes every signal); the display inputs
(`showPD`, `showPW`, `showAsia` …) do not change signals — the script sweeps PWH/PWL and
every session level whatever they say. ATR length 14 and `MAX_BACK` 4,500 are constants
in the script and here. Session strings are `SessionString` params (validated,
normalised to all days).

## Variants and instances (`config/instances.d/cisd_sweep.yaml`)

| Instance | Window | Entry | Target |
|---|---|---|---|
| `cisd_sweep_any_tp1_5m` | Any time (script default) | limit | TP1 |
| `cisd_sweep_any_tp2_5m` | Any time | limit | TP2 |
| `cisd_sweep_nyam_tp1_5m` | NY AM | limit | TP1 |
| `cisd_sweep_nyam_tp2_5m` | NY AM | limit | TP2 |
| `cisd_sweep_lonny_tp1_5m` | London + NY AM | limit | TP1 |
| `cisd_sweep_lonny_tp2_5m` | London + NY AM | limit | TP2 |
| `cisd_sweep_any_market_5m` | Any time | market at the next open (comparison) | TP2 |

All 5m (D10: the script's design chart), all 14 instruments, script defaults (D13),
one Paper 50K account per instance with `max_open_positions: 14` (one position per
instrument). TP1-only plus TP2-only reproduce a 50/50 split with the stop unchanged
(doc 13 P10). A 1m instance with a higher `min_body` waits for the parity check (D11).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| The entry is a resting limit at the CISD level, filled only if price comes back, expiring after 12 bars and cancelled when TP1 trades first; the script counts the trade from the signal bar as if filled | Doc 13 D7. The signal candle has already closed beyond the level, so only a limit reproduces the script's entry, stop and targets; the market comparison instance shows the other side |
| One target per instance (TP1 or TP2), no partial exit | Doc 13 D7/P10; the script defines no split |
| A replaced trade is exited at the next open with its P&L; the script drops it without an exit price (L721) | The lab must close a position somewhere; the next open is the first price after the new CISD |
| In limit mode an opposite CISD exits the trade at the next open instead of using the engine's resting reversal | A resting reversal keeps the old trade until the new limit fills, and for good if the new limit expires or is cancelled — the script ends it at once. Market mode uses the engine's reverse (same fills as exit + entry) |
| An untradable new CISD (D3) still ends the old trade | The script overwrites its trade with every CISD, tradable or not |
| Market comparison: no trade when the stop or target is not beyond the signal close; skipped when the next open passed either | Doc 13 D3; the account would refuse such levels against its mark anyway |
| Levels are rounded to the tick; a target that rounds onto the entry is a persisted `NO_TRADE` | Lab orders are on the tick grid; `script_*` metadata keeps the script's values |
| The 4,500-bar tracking limit (L764) closes the position at the next open (`SESSION_CLOSE`) | The lab has no "stop tracking"; a time exit is the closest |
| Fills, stops and targets follow the lab: the book can take profit on the fill bar only if it closes beyond the target, a bar opening beyond the target fills there, and the stop wins a bar that touches both | The script checks touches from the bar after the signal with the stop first (L751-755) |

## Parity notes

* **Fills on bid/ask.** The theoretical book fills, stops and targets at the mid on 5m
  bars; the accounts on bid/ask on 1m bars. The two can disagree (a limit the mid just
  touches, a target reached by less than half the spread), and then a cancel or a
  replace exit finds no order or position in the account (`NO_MATCHING_POSITION`, about
  2 % of exits in the synthetic smoke run). Doc 13 P8 would resolve the book on 1m
  bid/ask bars.
* **Day, week and month boundaries** (D8) are the catalog's: 17:00 New York for CFDs,
  FX, metals and MNQ (TradingView's CME day starts at 18:00, which contains the same
  bars), 00:00 UTC for crypto. A broker symbol with another session gives other
  PDH/PWH/PMH and other sweeps.
* **History.** PDH/PWH/PMH exist only once a whole period has been seen (`ctx.periods`
  leaves the partial first period out, like Pine's na). Forward paper trading warms up
  at most `forward.warmup_days` (10 by default): PDH is there from the start, PWH/PWL
  needs about 16 days and PMH/PML about 64 days of warm-up, so until then those sweeps
  cannot fire. TradingView's chart has them from its first months of history.
* **Sessions** use the bar's open time, half-open, in New York time. On the night the
  clocks go forward, London `0200-0500` starts at 03:00 EDT (the engine moves a time in
  the gap forward); TradingView's handling of that hour is unverified. Crypto runs the
  sessions on weekends too, as the script does.
* **Charts above 60 minutes** have no session levels and no window (L388, L680), exactly
  as the script; the lab's 4h bars are UTC-aligned (doc 05 §5.2.2).
* **Bar counts.** `sweepLook`, the pivots and the 4,500-bar limit count bars: thin crypto
  feeds with missing 5m bars differ from a gap-free chart.
* **Repainting.** The script signals on the live bar too; the lab sees closed bars only,
  which matches TradingView's history, not its realtime alerts.
* **Not checked against TradingView**: TradingView and the market-data APIs are not
  reachable from the development environment and no chart exports were provided.
  Correctness is shown by golden scenarios on hand-built New York tapes (winter, the
  first EDT week, summer, the DST night) and by an independent transcription of the
  Pine lines compared signal for signal on 41-70-day synthetic 5m runs, with and without
  closed weekends, on 5m, 15m, 1h and 4h, for every input
  (`tests/unit/strategies/cisd_sweep`).

## Warm-up

`meta.warmup_bars = 600` 5m bars (two days round the clock) for ATR(14), the 5/5
pivots and the session ranges. Forward paper trading adds `period_warmup_bars` for
`D`, `W` and `M`, which this module asks `ctx.periods` for (capped by
`forward.warmup_days`, see the parity notes). Signals during warm-up are discarded; a
limit placed then is forgotten after 12 bars, so a TP1 cancel or replace in the first
live bars may send one `EXIT_*` that finds no order (`NO_MATCHING_POSITION`).

## Licence

The script carries no licence statement (doc 13 §13.8: private use).

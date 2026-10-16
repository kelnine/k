# Script 10 · Jetstream v2 — 10_jetstream_v2.pine

Source: [`../received/10_jetstream_v2.pine`](../received/10_jetstream_v2.pine). Kind: **mixed**. Port complexity: **M** — The core trigger is small: an exact Pine SuperTrend plus WaveTrend for the strong variant. A faithful port still needs a user-chosen stop/exit design because the script defines none and the lab requires a stop, and the optional HTF variant needs TradingView-aligned 4H bars with completed-bar semantics. The live-bar repaint and SuperTrend path-dependency also have to be documented and handled in parity checks. Divergences and zones are non-trading and can be skipped.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### SuperTrend(10, 3) flip BUY / SELL (stop-and-reverse candidate)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** BUY on the bar where ta.change(dir) < 0, i.e. ta.supertrend(3.0, 10) direction goes from 1 to -1, and buyOK (L121, L166-167). SELL where ta.change(dir) > 0 and sellOK (L168). buyOK and sellOK are always true unless useHTF is on (default off, L30, L125-126). Pine's SuperTrend flips up when close > the current bar's ratcheted upper band; the band is derived from hl2 +/- 3 x ATR(10) and is effectively the previous bar's trail. The label is drawn on that bar, so the implied price is the signal close. Lab: MARKET at the next bar open. These signals are NOT gated by barstate.isconfirmed.
- **Stop:** None defined by the script. The natural candidate is the SuperTrend line st (L121). On a BUY bar st is the new lower band; while up it only ratchets upward (and mirrored for shorts), so trailing it with MOVE_SL never widens the stop. A user decision is required because the lab demands a stop.
- **Target / exit:** None defined. The implied exit is the next opposite flip. The TP diamonds are tpLong = upTrend and ta.crossunder(wt1, wt2) and wt1 > 60, and tpShort = not upTrend and ta.crossover(wt1, wt2) and wt1 < -60 (L171-172). The script calls them a 'consider trimming' hint, not an exit (L41 tooltip; alert texts L356-357).
- **Position rules:** Indicator only; it tracks no position. With useHTF off, dir alternates, so BUY and SELL strictly alternate: one signal per flip, no cooldown, no max per day, no session window, no flatten. With useHTF on, a flip against the 4H SuperTrend produces NO signal and is not deferred, so signals stop alternating and an open position gets no opposite signal to exit on. Proposed port: on_opposite_signal = reverse at next open, starting with the first flip after warm-up.
- **Timeframes:** Any chart timeframe. Optional HTF filter on 240 (4H) via request.security (L123). Scanner timeframes 5/15/60/240 (L129-132) are display-only.
- **Sessions (New York):** None (24h).
- **Defaults:** atrLen 10, mult 3.0, useHTF false, htfTF '240' (L26-31); WaveTrend src hlc3, n1 10, n2 21, sigLen 4; ob 60, os -60 (L48-55).

### STRONG BUY+ / SELL+ (SuperTrend flip with wt1 still on the other side of zero)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** strongBuy = tBuy and wt1 < 0; strongSell = tSell and wt1 > 0 (L169-170). wt1 = EMA21 of ci, where ci = (hlc3 - EMA10(hlc3)) / (0.015 x EMA10(|hlc3 - esa|)), or 0 when de is 0 or na (L147-151). It fires on the same bar as the BUY/SELL. In 'Labels' style the plain BUY/SELL label is suppressed and replaced by BUY+/SELL+ (L191-194). In 'Triangles' and 'Compact' styles strong signals are not distinguished at all (L195-198). Lab: MARKET at the next open.
- **Stop:** None defined.
- **Target / exit:** None defined. TP diamonds are hints only (L41).
- **Position rules:** A strict subset of setup 1. As a separate instance, the exit rule must be decided: exit on any opposite flip, or only on SELL+/BUY+.
- **Timeframes:** Any chart TF.
- **Sessions (New York):** None (24h).
- **Defaults:** Same as setup 1. Threshold is wt1 vs 0, not vs ob/os.

### WaveTrend regular divergence (Bull div / Bear div)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** bullDiv is set on the bar where ta.pivotlow(wt2, 5, 5) confirms, 5 bars after the wt2 pivot (L266, L273-283). The conditions: price low at the wt2-pivot bar (low[5]) < low at the previous wt2 pivot-low bar; wt2 at the pivot > previous pivot's wt2; previous pivot's wt2 < 0. bearDiv mirrors this with highs and requires the previous pivot's wt2 > 0 (L267, L289-299). It is exposed only as an alertcondition (L358-359) and a back-dated line/label in the oscillator pane.
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None. The reference pivot is replaced at every new wt2 pivot, whether or not it produced a divergence (L281-283, L297-299).
- **Timeframes:** Any chart TF.
- **Sessions (New York):** None.
- **Defaults:** divLb 5, showDiv true (L76-77).

### VolMom 'Bull' / 'Bear' WaveTrend OB/OS cross labels

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** 'Bull' label when ta.crossover(wt1, wt2) and wt2 <= -60; 'Bear' label when ta.crossunder(wt1, wt2) and wt2 >= 60 (L259-263). Drawn only with oscStyle 'VolMom' (the default) and showLabels true, and gated on barstate.isconfirmed. There is no alertcondition for these.
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None.
- **Timeframes:** Any chart TF.
- **Sessions (New York):** None.
- **Defaults:** ob 60, os -60, oscStyle 'VolMom', showLabels true.

### Supply & demand zones (levels only)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No trade rule. Supply: when ta.pivothigh(high, 10, 10) confirms (10 bars after the swing), a box is drawn from high[10] down to max(open[10], close[10]), starting at bar_index - 10 and extended right (L207, L210-213). Demand: when ta.pivotlow(low, 10, 10) confirms, a box from min(open[10], close[10]) down to low[10] (L208, L214-217). A zone is deleted when a confirmed bar closes above the supply top or below the demand bottom (L218-228). At most 6 zones per side are kept; the oldest is dropped (L212-213, L216-217).
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** None.
- **Timeframes:** Any chart TF.
- **Sessions (New York):** None.
- **Defaults:** sdLen 10, sdMax 6, showSD true (L80-82).

## Data needs

Chart-timeframe OHLC: hl2 for SuperTrend, hlc3 for WaveTrend. Volume is NOT needed for any signal; it only feeds the relative-volume heatmap and dashboard (L160-163). Optional 4H bars for the HTF filter (off by default), aligned the way TradingView builds 4H bars from the symbol's session start. Scanner timeframes 5/15/60/240 only feed a display table and need not be ported. No daily/weekly bars and no intrabar data. Warm-up >= 300 bars recommended, for ATR(10) RMA convergence, SuperTrend band path-dependency and the WaveTrend EMA10/EMA21/SMA4.

## Engine features needed

- Stop-and-reverse at the next open (on_opposite_signal = reverse; exists)
- A mandatory protective stop on every entry. Either a fixed protective stop, or a trailing stop updated each bar via MOVE_SL onto the SuperTrend line (exists; the line never widens)
- EXIT_LONG / EXIT_SHORT at the next open on a close-based condition (exists), needed if an HTF-suppressed flip should still close the position
- Optional: 4H context bars aligned to TradingView's session-anchored 4H boundaries, using completed bars only (no developing-bar lookahead), for the HTF-filter variant
- Optional and not in the engine today: partial exits, only if the user wants TP diamonds to trim positions

## Building blocks

- SuperTrend in exact Pine ta.supertrend semantics: src hl2, ATR = RMA(TR, 10), factor 3. Bands use nz(prev band) = 0 on the first bar and ratchet (lower band = new if new > prev or close[1] < prev, else prev). Direction is 1 while atr[1] is na. The flip test compares close with the CURRENT bar's ratcheted band, and trend state is detected by float equality prevSuperTrend == prevUpperBand
- WaveTrend (LazyBear variant): src hlc3, esa = EMA10, de = EMA10(|src - esa|), ci = (src - esa) / (0.015 x de) with ci = 0 when de == 0 OR de is na, wt1 = EMA21(ci), wt2 = SMA4(wt1); crosses of wt1 vs wt2
- Pine ta.change on an int series (flip = +/-2, na on the first bar)
- Pivot high/low ta.pivothigh/ta.pivotlow with left = right = N. Used on wt2 with N = 5 and on bar high/low with N = 10; tie handling must match Pine
- Regular-divergence detector on consecutive wt2 pivots (previous pivot must be below or above 0; price is taken at the wt2-pivot bar, not at the price swing)
- Supply/demand zone: wick-to-body box at a confirmed 10/10 swing, invalidated by a close beyond its far edge, FIFO cap of 6 per side
- HTF SuperTrend via request.security with lookahead_off (optional variant)
- Display-only (no need to port for trading): EMA 21/55 ribbon, MACD 12/26/9, candle-body money flow SMA60, relative volume vs SMA20, trend-scanner scores

## Parity risks

- BUY/SELL/BUY+/SELL+/TP diamonds and their alertconditions are NOT gated by barstate.isconfirmed (L166-172, L191-200, L352-357). On the live bar they appear as soon as the current price crosses the band and can vanish before the close. Alerts set to 'Once per bar' fire intrabar. A closed-bar port matches TradingView's HISTORICAL bars and 'Once per bar close' alerts only.
- The script's signal is at the flip-bar close; the lab fills at the next open, so every reversal is offset by the close-to-open move (large at session breaks and weekends).
- SuperTrend is path-dependent. Band ratcheting starts from nz(prev) = 0 and direction is forced to 1 until ATR exists, so early flips depend on where history starts. Load ample warm-up and compare flips only after the first post-warm-up flip.
- Replicate the built-in exactly: the flip test uses the current bar's ratcheted band (not the previous plotted trail), and the trend-state check is an exact float equality prevSuperTrend == prevUpperBand. A 'textbook' SuperTrend implementation can disagree on edge bars.
- Pine ta.atr/ta.rma and ta.ema seeding and warm-up must be replicated; WaveTrend's ci falls back to 0 (not na) while de is na or 0 (L149), which seeds wt1 differently from NumPy NaN propagation.
- HTF filter (if enabled): request.security(..., '240', ..., lookahead_off) without [1]. On historical bars each chart bar sees the last COMPLETED 4H value, and the just-closed 4H value appears on the chart bar that closes with the 4H bar. In realtime it sees the developing 4H value. Live signals therefore differ from history after reload. 4H bar boundaries must also match TradingView's session-anchored 4H grid (CME 17:00 CT, FX/CFD 17:00 ET, crypto 00:00 UTC).
- With the HTF filter on, an na HTF direction (warm-up or missing data) blocks buys but allows sells (L124-126).
- Pivot-based outputs (divergence lines and labels, S/D boxes) are back-dated to the swing bar (bar_index - 5 or bar_index - 10) but only known 5 or 10 bars later. Their creation is not confirmation-gated, so on the live bar the developing bar counts as a right-side bar and a pivot or zone can appear intrabar and then disappear. Pine pivot tie rules must be matched.
- S/D zones are deleted once broken (L221-228), so the TradingView chart only shows surviving zones. Any study of 'how zones held' from the chart is survivorship-biased.
- If the chart timeframe is above 5m, the scanner's 5m request.security (L129) is a lower-timeframe request. It is display-only and does not affect signals.

## Behaviour found in the code

- None of the trade-relevant signals are confirmation-gated (L166-172, L191-200, L352-357): BUY/SELL/BUY+/SELL+/TP can flash intrabar on the live bar. Only the VolMom labels (L259) and zone removal (L218) check barstate.isconfirmed.
- HTF filter asymmetry: htfUp = htfDir < 0 is false while htfDir is na, so buyOK = false and sellOK = true. Sells pass and buys are blocked whenever the HTF series is unavailable (L124-126).
- With useHTF on, a suppressed flip is never re-issued. The next signal can only come from the following flip, so a trader following the labels has no exit signal while the chart trend runs against them.
- Inconsistent OB/OS reference: TP diamonds test wt1 against +/-60 (L171-172), while the VolMom Bull/Bear labels test wt2 (L260-262).
- The STRONG threshold is wt1 < 0 / > 0, not oversold/overbought. The 'momentum washed out' wording (L169, L354) overstates it.
- WaveTrend warm-up: ci = 0 when de is na (L149) because the na comparison is false, so wt1's EMA is seeded with zeros rather than starting later.
- Pivot outputs (zones, divergences) are created without confirmation gating (L210-217, L273-299). On the realtime bar they can appear and be rolled back within the bar. The sdMax FIFO (L212-217) drops the oldest zone even if it is still unbroken.
- Divergence reference pivots are overwritten at every new wt2 pivot regardless of outcome (L281-283, L297-299), and only regular (not hidden) divergences are detected.
- The scanner's four request.security calls (L129-132) always run even in 'Methods' mode; on charts above 5m the 5m call is a lower-timeframe request. This is display-only, with no signal impact.
- Dashboard bias score, MTF score, money flow and relative volume are display-only and never filter signals (L137, L157-163, L175-178).

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| partly | 10.1 BUY when SuperTrend (ATR 10, multiplier 3) flips up, SELL when it flips down: stop-and-reverse, always in the market. | The BUY/SELL triggers are correct. 'Stop-and-reverse, always in the market' is an interpretation, not something the script defines: there is no position, stop or exit. With the HTF filter off, BUY and SELL do strictly alternate, so a SAR reading is natural. With it on, suppressed flips are lost, signals need not alternate, and a 'position' can be left with no exit signal. |
| confirmed | 10.2 BUY+/SELL+ are the same flips while WaveTrend wt1 is still on the other side of zero, i.e. a subset of the normal signals. | L169-170: strongBuy = tBuy and wt1 < 0; strongSell = tSell and wt1 > 0. They inherit buyOK/sellOK through tBuy/tSell. L191-194: in 'Labels' style the plain label is hidden when the strong one shows. L195-198: Triangles and Compact styles do not distinguish strong signals. |
| partly | 10.3 SuperTrend only flips when a candle CLOSES beyond the trail line (not on a wick). | On completed or historical bars it is close-based. But the band compared against is the current bar's band (from this bar's hl2 and ATR, ratcheted), which is normally the previous trail value. On the live bar, 'close' is the current price, so BUY/SELL labels and 'Once per bar' alerts appear as soon as price trades beyond the band intrabar, and can disappear if the bar closes back inside. |
| confirmed | 10.4 Take-profit diamonds are described by the script itself as a 'consider trimming' hint, not an exit. | L41 tooltip: "WT cross against the trend while stretched past the OB/OS level — a 'consider trimming' hint, not an exit signal." L356-357 alert texts: '...consider trimming longs/shorts'. L171-172: tpLong = upTrend and wtCrossDown and wt1 > 60; tpShort = not upTrend and wtCrossUp and wt1 < -60. These are independent of whether any BUY/SELL occurred, can fire several times per trend, and ignore the HTF filter. |
| confirmed | 10.5 With the higher-timeframe filter on (off by default), the script reads the 4H SuperTrend while that bar is still forming (lookahead_off without [1]), so live signals can differ from history. | L30: useHTF default false; its tooltip says 'the HTF value updates as its bar forms'. L31: htfTF '240'. L123: request.security(syminfo.tickerid, htfTF, ta.supertrend(mult, atrLen), lookahead = barmerge.lookahead_off), with no [1]. L125-126 gate tBuy/tSell. |
| confirmed | 10.6 Divergences and supply/demand zones are drawn back on the swing bar but only known 5-10 bars later. | Divergences: L266-267 use ta.pivotlow/pivothigh(wt2, 5, 5). L279-280 and L295-296 draw the line from the previous pivot bar to bar_index - divLb and the label at bar_index - divLb, so they are known 5 bars later. bullDiv/bearDiv (and their alerts L358-359) fire on the detection bar. Zones: L207-208 use pivots(high/low, 10, 10). L211/L215 call box.new(bar_index - sdLen, ...), so zones are back-dated by 10 bars; the L81 tooltip says so. |

## Questions this script raises

- **The script defines no stop or exit for the BUY/SELL flips, but every lab entry needs a stop. How should trades be stopped and exited?** Options: Stop-and-reverse on the close-based flip (exit and reverse at next open), plus a protective stop fixed at the SuperTrend line of the signal bar +/- 1 x ATR(10); A resting stop on the SuperTrend line, trailed every bar with MOVE_SL. It can be hit by a wick and exits earlier than the chart's flip, leaving the position flat until the next flip; A fixed ATR stop and R-multiple target (not in the script). Recommended: Stop-and-reverse on the close-based flip with a protective stop at the SuperTrend line +/- 1 x ATR(10). Run the trailing-line stop as a second instance if wanted. — Trade timing stays identical to the signals the user sees on TradingView, and the buffered stop only catches gaps or crashes. A resting stop on the line changes the strategy, because wicks would exit trades that TradingView keeps.
- **If the 4H HTF filter variant is run, which 4H value is used, and what happens when a chart flip against the 4H trend is suppressed while a position is open?** Options: Completed 4H bar only; a suppressed flip exits the position without reversing; Completed 4H bar only; a suppressed flip is ignored and the position is held; Developing 4H value, as TradingView does in realtime. Recommended: Completed 4H bar only; a suppressed flip exits the position (EXIT at next open) without reversing — Completed bars match TradingView's history and avoid lookahead. Exiting on the chart flip keeps the trend exit while the filter only gates new entries; otherwise a position would have no exit at all.
- **Should TP diamonds do anything?** Options: Ignore them; Close the whole position at the next open; Partial close (needs a new partial-exit engine feature). Recommended: Ignore them — The script explicitly says they are a 'consider trimming' hint, not an exit (L41), and partial exits are not supported by the engine today.
- **Should BUY+/SELL+ run as a separate 'strong only' instance, and how does it exit?** Options: No, only all flips; Yes; exit on any opposite flip (plain SELL/BUY included); Yes; exit only on an opposite strong signal. Recommended: Run both instances: 'all flips', and 'strong only' that exits on any opposite flip — Strong signals are a parameterised subset (a variant of one strategy). The trend reversal is the plain flip, so waiting for an opposite '+' signal would hold losing trends.
- **Which timeframes and directions should run?** Options: 5m only, long and short; 5m and 15m, long and short; Long-only for crypto and indices. Recommended: 5m and 15m as separate instances, long and short — The script is symmetric and timeframe-agnostic. These match the user's entry and confirmation timeframes.
- **Should divergences, VolMom labels or supply/demand zones be built as strategies?** Options: No; leave them as indicator/levels only; Yes, with user-defined stops and targets. Recommended: No; do not port them as strategies now — None of them has a stop or exit in the script. Inventing rules would violate the faithful-port rule.

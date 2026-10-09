# Script 4 · Combined SMC Suite [OB + Channels + PSAR + KCharts + DepthFlow]

Source: [`../received/04_combined_smc_suite.pine`](../received/04_combined_smc_suite.pine). Kind: **mixed**. Port complexity: **L** — The only near-tradable part, the PSAR strategy, is about M on its own. It needs an exact port of TradingView's ta.sar (unclamped projection test, bar-1 initialisation), RMA-based DMI/ADX and EMA200 with warm-up, stop-and-reverse sequencing, and a stop decision. The rest is five levels-only modules that each need their own parity checks: the LuxAlgo volume-pivot OB, AlgoAlpha volatility channels (population stdev, highestbars ties, variable-length highest/lowest, overlap rule), session VWAP, session-anchored 1H/4H levels, and pivot sweeps/displacement. The volume profile and dominance table are last-bar visuals and should not be ported.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### 200 EMA filtered Parabolic SAR (long/short, stop-and-reverse)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Evaluated at the close of the bar where the SAR flips. Long needs all of these: psSar < close and NOT (psSar[1] < close[1]) (L603, L607, L610); close > EMA(close,200) (L602, L613); ADX > 20 from ta.dmi(DI length 14, ADX smoothing 14) (L605, L615); and not already long (L630). Short is the mirror: psSar > close and not psSar[1] > close[1], close < EMA200, ADX > 20, not already short (L611, L614, L631). Only the flip bar itself can trigger. If a filter fails on that bar, nothing is entered for the rest of that SAR leg. Marker at L1044/L1045; alert at L1131/L1133 fires once per bar close. Because this is an indicator it gives no order type or price. The implied price is the flip-bar close, which the lab fills as a market order at the next bar's open.
- **Stop:** None defined. The only way a trade ends is the opposite SAR flip, evaluated on the close. The SAR value is the obvious stop candidate (see decisions).
- **Target / exit:** No target and no partial exits. A long exits when it is open and the SAR flips above the close: psExitLong = psInLong and psFlipDn (L621), marker 'EL' (L1046), alert (L1135). Shorts mirror this (L622, L1047, L1137). Exits ignore the EMA200 and ADX filters. They are signalled at the flip-bar close, so the lab exit is the next bar's open.
- **Position rules:** Only one position at a time: the var flags psInLong and psInShort (L617-L638) are mutually exclusive. On a flip-down bar the long is closed first (L624-L625). A short opens on that same bar only if close < EMA200 and ADX > 20 (stop-and-reverse, L631-L638); otherwise the strategy stays flat until the next qualifying flip. Flip-up bars mirror this. There is no limit on trades per day, no cooldown, no session window and no end-of-day or weekend flatten. Positions stay open until the opposite flip.
- **Timeframes:** Chart timeframe only. This module makes no HTF request and the script names no timeframe.
- **Sessions (New York):** None. Runs 24h on every bar.
- **Defaults:** PSARstart 0.02, Increment 0.02, Maximum 0.2 (L575-L577). MaSlowLength 200 (L573). DI Length 14, ADX Smoothing 14, Threshold 20 with a strict '>' (L579-L581, L615). MaFast 7 and MaMed 21 only drive the band fill (L600-L601, L1057) and play no part in signals.

### LuxAlgo volume-pivot order blocks (formation / mitigation)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. A bullish OB is recorded when ta.pivothigh(volume,5,5) confirms (L223) while os==1. os is a sticky state: it becomes 1 when low[5] is below the lowest low of the 5 bars after it and 0 when high[5] is above their highest high (L210-L220). Bullish zone: top hl2[5], bottom low[5], midline avg, drawn from time[5] (L232). Bearish OB when os==0: top high[5], bottom hl2[5] (L238). Alerts 'order block detected' at L1112-L1115.
- **Stop:** None.
- **Target / exit:** None. 'Mitigated' (L243-L244, alerts L1116-L1119) only means the zone is deleted. A bullish zone is deleted when the lowest low of the last 5 bars ('Close' mode: lowest close) goes below its bottom. A bearish zone is deleted when the highest high (or highest close) of the last 5 bars goes above its top.
- **Position rules:** Not applicable. Every unmitigated OB stays in the arrays, but only the newest 3 per side are drawn (L249-L250).
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** Volume Pivot Length 5, Mitigation 'Wick', 3 bullish and 3 bearish drawn.

### AlgoAlpha breakout channel break

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. A channel is created on ta.crossover(upper, lower), where upper and lower are the highestbars/lowestbars position of stdev(14) of normalized price within 15 bars (L375-L388). Two more conditions: duration > 10, where duration = bars since the last reverse crossover (L391), and the box spans the highest high and lowest low over that duration (L392-L393, L418-L426). With Nested off, a box that overlaps an active channel is rejected (L341-L348, L419). A bullish break is avg(open, close) > box top with Strong Closes on (L432); a bearish break is avg(open, close) < box bottom (L441). The marker is drawn at the opposite edge (L999-L1000). Alerts at L1122-L1127.
- **Stop:** None. The marker sits at the far channel edge but nothing uses it as a stop.
- **Target / exit:** None.
- **Position rules:** Not applicable. Several non-overlapping channels can be active, and one bar can break more than one of them.
- **Timeframes:** Chart timeframe. The 1m up/down volume (L285, L396) only feeds the gauge and volume candles.
- **Sessions (New York):** None.
- **Defaults:** Normalization Length 100, Box Detection Length 14, stdev 14, Strong Closes true, Nested Channels false, Max Historical Channels 50 (drawings only).

### KCharts EMA 9/21 pullback tap

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. Up tap: EMA9 > EMA21 and close > EMA21 and low <= EMA9 and close > EMA9 (L735, L740). Down tap mirrors it (L736, L741). Markers at L1065-L1066, alerts at L1140-L1143.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable.
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** Source close, fast 9, slow 21.

### Close through previous completed 1H / 4H high or low

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. Signals are ta.crossover(close, previous 1H high) and ta.crossunder(close, previous 1H low), plus the same for 4H (L1105-L1108). The previous levels come from request.security(tf, [high[1], low[1]], lookahead_on) (L765-L766). Alerts at L1144-L1151.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable.
- **Timeframes:** Chart timeframe plus 60 and 240 HTF bars.
- **Sessions (New York):** None. HTF bucket boundaries follow TradingView's session for the symbol.
- **Defaults:** Timeframe A '60', Timeframe B '240'.

### Close across session VWAP

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. Signal is crossover/crossunder(close, VWAP(hlc3)), with VWAP reset on timeframe.change('D') by default (L745-L758, L786-L787). Alerts at L1152-L1155 are gated by 'Show VWAP'.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable.
- **Timeframes:** Chart timeframe; daily reset.
- **Sessions (New York):** Resets at the symbol's TradingView trading-day boundary, not at a NY time.
- **Defaults:** Anchor Session, source hlc3, bands off.

### DepthFlow liquidity sweep (5/5 pivot)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. Buy-side sweep: high > the last confirmed ta.pivothigh(5,5) and close < it, and the previous bar was not also such a sweep against the current level (L972-L983). Sell-side sweep mirrors it (L985). Labels at L1089-L1090, alerts at L1158-L1161.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable. A level is never consumed (see issues).
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** Swing strength 5.

### DepthFlow displacement candle

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. Condition is |close-open| > 1.6 × ATR(14); direction is the candle colour, with close >= open counted as up (L987-L990). Labels at L1091-L1092, alerts at L1162-L1165.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable.
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** ATR 14, multiplier 1.6.

### Confluence alert: PSAR entry + channel breakout on the same bar

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Alert only: psLong and bcBullishBreakout on the same bar (L1168-L1169), with the short mirror at L1170-L1171. These events are a subset of the PSAR entries. Building this as a strategy would combine two modules.
- **Stop:** None.
- **Target / exit:** None of its own. Only the PSAR flip exit would apply.
- **Position rules:** Inherits the PSAR state machine.
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** PSAR defaults plus channel defaults.

## Data needs

PSAR strategy: chart-timeframe OHLC only. It needs no volume, no HTF data and no daily/weekly bars, but needs a long warm-up (EMA200 plus RMA-based ADX; ≥1000 bars recommended). Levels-only modules: bar volume (OB volume pivots, VWAP, DepthFlow), 60m and 240m bars aligned to TradingView's per-symbol session (previous completed high/low via lookahead_on+[1], plus the developing high/low), and per-instrument trading-day boundaries for the VWAP reset (W/M/3M/12M only if the anchor is changed). The 1m intrabar up/down volume from TradingView/ta/10 requestUpAndDownVolume('1') (L396) feeds only the channel volume candles and gauge, so it can be dropped. Nothing external is used.

## Engine features needed

- Close-confirmed signal leading to a market entry at the next bar's open (already in the lab)
- Signal-driven exit: close the position at the next open after an opposite SAR flip
- Stop-and-reverse: exit long and enter short (or the reverse) at the same next open
- Trailing stop updated every bar, needed only if the user picks the intrabar SAR-stop variant. The SAR is monotone within a leg, so this fits the MOVE_SL never-widens rule
- Exact TradingView ports of ta.sar, ta.dmi (RMA with fixnan), ta.ema and ta.rma, with explicit warm-up
- Persistent per-instance position state that carries across sessions and weekends (no time exit)
- Levels-only: HTF bars (60/240) aligned without lookahead, using TradingView's session-anchored 4H buckets
- Levels-only: session-anchored VWAP with a reset at each instrument's trading-day boundary, plus bar volume
- Optional, visual-only: lower-TF (1m) up/down volume

## Building blocks

- Parabolic SAR: TradingView's reference algorithm. On each bar the projected SAR (prev + AF×(EP−prev)) is tested against low/high BEFORE it is clamped to low[1]/low[2] (or high[1]/high[2]). Initialisation at bar_index==1 uses close>close[1]. AF rises only on a new extreme. Flip here = sign change of SAR vs close (L607-L611), not the internal trend flag
- DMI/ADX via ta.dmi(14,14): RMA of TR/+DM/−DM, fixnan, ADX = RMA of |+DI−−DI|/sum
- EMA 200 trend filter on close (EMA 7/21 are visual only)
- LuxAlgo volume-pivot order block: ta.pivothigh(volume,5,5), sticky os state from high[5]/low[5] against the 5-bar highest/lowest, bullish zone hl2..low, bearish zone high..hl2, mitigation when the 5-bar lowest low (or highest high) breaches the far edge, 'Close' mode uses closes. This variant differs from script 5's OB
- AlgoAlpha volatility channel: (close−lowest(low,100))/(highest−lowest), population ta.stdev(…,14), highestbars/lowestbars over 15 bars, crossover state, variable-length ta.highest/ta.lowest over bars since reset, non-overlap rule, break on body midpoint
- EMA 9/21 band pullback-tap detector
- Session VWAP (hlc3) with σ bands, reset on timeframe.change('D')
- Previous completed HTF (1H/4H) high/low without lookahead, plus the developing HTF high/low
- Swing pivot ta.pivothigh/pivotlow(high/low,5,5) with last-level memory; sweep = wick beyond the level and close back inside, with no repeat on consecutive bars and the level never consumed. This variant differs from script 5's 20-bar sweep
- Displacement: body > 1.6×ATR(14)
- Volume-by-price profile (300 bars, 120 bins, nodes ≥0.55×peak) and close-location buy/sell split. Last bar only and display only, so not needed for the lab

## Parity risks

- ta.sar internals: TradingView tests the UNCLAMPED projected SAR for the current bar against low/high and clamps afterwards. The bar_index==1 initialisation means the SAR path depends on where chart history starts until the first reversal. A library PSAR (TA-Lib, pandas-ta) clamps before testing and will flip on different bars
- The flip is defined as SAR versus close (L607-L611). If SAR equals close on a bar, the following bar can register a 'flip' with no SAR reversal
- Entries and exits are signalled at the flip-bar close, but the lab fills at the next bar's open. SAR flip bars are usually wide-range bars, so the gap between close and next open is material
- Warm-up: EMA200 seeding, RMA seeding in DMI/ADX, and the psInLong/psInShort state all depend on the first bar of history. TradingView's limited intraday history means the lab must warm up long enough (≥1000 bars) and start flat
- No barstate.isconfirmed gating: on the realtime bar the EMA/ADX filters, and therefore the Long/Short/EL/ES markers, can appear and disappear intrabar. The alerts use alert.freq_once_per_bar_close, so they match close-confirmed logic
- OB module: drawings are back-dated to time[5] but only known 5 bars later. Volume pivots depend on the volume feed (CFD/FX tick volume on TradingView differs from the lab feed). Pivot tie-handling must match ta.pivothigh. An OB can be mitigated on the bar it is created
- Channels: ta.stdev is population (ddof=0), not the pandas default. Tie-breaking in ta.highestbars/lowestbars must match. ta.highest/lowest use a series (variable) length. Boxes are back-dated by 'duration'. Which channels exist depends on history (the overlap rule)
- HTF levels: prev 1H/4H with lookahead_on+[1] does not repaint, but 4H bucket anchors follow TradingView's per-symbol session (CME 18:00 ET, OANDA FX 17:00 ET, crypto 00:00 UTC). The 'current period' high/low from request.security without lookahead (L767-L768) shows the previous completed values on historical bars and developing values in realtime
- VWAP resets on timeframe.change('D'), which follows the symbol's TradingView session. The lab catalog's day boundary must match
- ta.crossover/crossunder against a level that steps at an HTF period start (L1105-L1108) or a VWAP reset compares close[1] with the OLD level, so the port must replicate the 'a>b and a[1]<=b[1]' semantics exactly
- The DepthFlow volume blocks and dominance are recomputed on the last bar only (L838, L956). They cannot be reproduced historically as the user sees them
- sigMark keeps only the last 150 KCharts/DepthFlow markers, so the user cannot see older markers on TradingView when comparing with the lab

## Behaviour found in the code

- Module switches do not silence alerts. psLong, psShort and the exits (L621-L631) do not include psEnable. kcPbUp/Dn (L740-L741) and the HTF crosses (L1105-L1108) do not include kcEnable, kcShowTf1/2, kcShowPrev or kcFits. DepthFlow sweeps and displacement (L983-L990) are gated by dfShowSweeps/dfShowDisp but not dfEnable. With 'Any alert() function call' active, a module the user switched off keeps firing alerts (L1130-L1165), including the PSAR side of the confluence alert.
- PSAR enters only on the flip bar (L630-L631). If the EMA200 or ADX filter fails at that moment, no trade happens for that leg even if both filters pass a bar later. Exits ignore the filters.
- The PSAR flip is SAR vs close (L607-L611), not ta.sar's internal direction. When SAR equals close, the next bar can print a 'flip' Long/Short without a SAR reversal.
- The 'current period' 1H/4H high/low (L767-L768) is read with request.security without lookahead. On historical bars it equals the previous completed period's values until the last chart bar of the period, and only in realtime does it develop as the tooltip at L670-L671 describes. Visual only.
- The HTF break alerts (L1105-L1108) use crossover against a level that steps at each new period. On the first chart bar of a new period the [1] side is the OLD level, so a breakout of the new level on that first bar is missed whenever the previous period already closed above (or below) the older level.
- DepthFlow sweep levels are never consumed (L975-L985). The same pivot can be 'swept' again and again, even after price has closed through it and come back.
- The order-block mitigation target is the lowest low (or highest high) of the last 5 bars (L210-L218, L243-L244). An OB whose candle low was undercut inside its own 5-bar confirmation window is deleted on the bar it is created and never appears. The mitigation loop and the channel loop were also rewritten back-to-front (L148-L164, L430-L454), so they may not match the original LuxAlgo/AlgoAlpha indicators if the user also runs those.
- Several channels can be active with Nested off as long as they don't overlap. One bar can break several of them, and bcUpbreak/bcDownbreak keep only the last one processed (L430-L448).
- OBs and VWAP need volume. On TradingView symbols without volume OBs never form and VWAP is na. On CFD/FX symbols the volume is broker tick volume.

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| partly | 4.1 The only complete strategy is the 200 EMA filtered Parabolic SAR: long when SAR flips below price AND close > EMA200 AND ADX(14) > 20; exit long when SAR flips back; shorts mirror; no target. | The trade logic is right, but 'complete' overstates it: the script defines no stop price, only a close-confirmed opposite flip, so the lab still needs a stop decision. Further details: (a) the flip is SAR vs close at the bar close (L607-L611); (b) only the flip bar can enter, so if EMA/ADX fail on that bar the whole SAR leg is skipped; (c) exits ignore the filters, and on a flip that closes a long a short opens on the same bar only if its own filters pass, otherwise the strategy is flat; (d) ADX is ta.dmi(DI 14, smoothing 14) with a strict '>'; (e) the EMA 7/21 are visual only. |
| confirmed | 4.2 The PSAR section was reconstructed from screenshots of the settings panel (per the header), not from the original code. | L7-L8: '200 EMA Filtered Parabolic SAR — reconstructed from its settings panel (inputs / style / signal shapes), since only screenshots were available.' The rules at L600-L638 are therefore the reconstructor's interpretation. For example the 7/21 EMAs only drive a fill (L1057) and the exit rule is inferred. |
| partly | 4.3 The indicator marks the PSAR exit at the close of the flip bar, while a trailing stop at the SAR level would exit intrabar when price touches the SAR. | The indicator gives no exit price at all. It marks the flip bar and alerts at its close, and in the lab that exit fills at the NEXT bar's open, not at the flip-bar close. For the trailing stop, the level that triggers TradingView's flip on bar t is the projected SAR for bar t (SAR[t-1] + AF×(EP−SAR[t-1]), tested before the low[1]/low[2] clamp), not the dot plotted on bar t-1. A stop placed at the previous dot is further from price and can miss flips that TradingView records. |
| confirmed | 4.4 The confluence alerts fire when a PSAR signal and a channel breakout happen on the SAME bar. | L1168-L1171: 'if psLong and bcBullishBreakout' and 'if psShort and bcBearishBreakout', using the same-bar booleans, with alert.freq_once_per_bar_close. Only PSAR entries (not exits) count. psLong is not gated by psEnable (L630), so the alert still fires with the PSAR module switched off; bcBullishBreakout does need bcEnable, because boxes are only created when the module is on (L418). |
| confirmed | 4.5 Order blocks, channel breaks, EMA pullback taps, prior 1H/4H high/low and VWAP crosses, sweeps and displacement have no exits. | OB L206-L250 and L1112-L1119; channels L418-L454 and L1122-L1127; taps L740-L741 and L1140-L1143; HTF crosses L1105-L1108 and L1144-L1151; VWAP L786-L787 and L1152-L1155; sweeps and displacement L983-L990 and L1158-L1165. None has stop, target or exit logic. OB 'mitigated' only deletes a zone, and the channel marker price (L999-L1000) is never used as a stop. They have no entries in any trade sense either; they are events or levels only. |
| confirmed | 4.6 The LuxAlgo order-block section is CC BY-NC-SA 4.0 and the AlgoAlpha channel section is MPL 2.0. | L3-L6 and L10 in the header. Not covered by the claim: the PSAR reconstruction, KCharts and DepthFlow sections carry no license statement, and the script imports TradingView/ta/10 (L19). NonCommercial and ShareAlike terms apply to any redistributed port of the OB section. |

## Questions this script raises

- **The PSAR setup has an entry and a flip exit but no stop price, and the lab requires a stop_loss on every signal. Which exit/stop model should it use?** Options: A: faithful. Exit at the next open after a close-confirmed opposite flip; protective stop fixed at the SAR printed on the signal bar (the prior leg's extreme), never moved; B: intrabar trailing. Stop = TradingView's projected SAR for the next bar, updated every bar; exit when touched; Run A and B as two variant instances. Recommended: Run A as the primary instance and B as a variant instance — A reproduces the EL/ES markers the user sees and satisfies the mandatory stop. B is how a SAR is normally traded and exits on the same flip bar at a different price. Comparing them shows how much the close-confirmation costs.
- **Which chart timeframe(s) and instruments should the PSAR strategy run on? The script specifies none.** Options: 5m; 15m; 1H; 15m primary + 5m variant. Recommended: 15m primary plus a 5m variant, on all listed instruments — It is a trend-following flip system on the chart timeframe. 15m matches the user's confirmation timeframe, and 5m matches their entry timeframe.
- **Should the PSAR strategy be limited to sessions (London/NY)?** Options: No filter (24h, faithful); London + NY only; NY only. Recommended: No filter (faithful) — The script has no session logic. A session filter would be a new rule.
- **Should the confluence alert (PSAR entry + channel breakout on the same bar) become its own strategy?** Options: Do not build; Build it as a filtered PSAR variant. Recommended: Do not build unless the user asks — It combines two modules, and the user's rule is never to combine indicators unless explicitly asked.
- **What should happen to the levels-only modules (OBs, channels, pullback taps, 1H/4H levels, VWAP, sweeps, displacement)?** Options: Port them as reusable primitives only; Defer them; Invent entry/stop/exit rules. Recommended: Port them as reusable primitives (no strategies) when a strategy needs them — None of them defines an entry, stop or exit, so any trade rule would be invented.

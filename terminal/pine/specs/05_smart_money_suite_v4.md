# Script 5 · Smart Money Suite v4 [AlgoAlpha]

Source: [`../received/05_smart_money_suite_v4.pine`](../received/05_smart_money_suite_v4.pine). Kind: **mixed**. Port complexity: **M** — There is one bar-close strategy with a fixed bracket and no HTF, intrabar or volume dependency. A faithful port needs exact pivots (40/40 and 10/10 with matching ties), the BOS state machine with un-consumed levels and the before-update crossover semantics, FIFO-capped OB/FVG registries with current-ATR invalidation, and EMA/RSI/ATR with TradingView seeding. Parity hinges on the crossover [1] semantics, pivot ties and history start. The levels-only extras (S&D, key levels, AM range, sweeps, volume sentiment) are small. The scanner, dashboard and Fib zone are display-only and need no port.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### Sniper: BOS + ≥3-of-4 score with fixed 2R bracket (long/short)

*Fully defined by the script (entry, stop and exit):* **yes**

- **Entry:** Evaluated at bar close. Long fires when sniper_on and bos_bull and sniper_bull >= sniper_min, default 3 (L628). bos_bull = bos_on and not na(lsh) and ta.crossover(close, lsh) (L385, L395). lsh is the most recent confirmed ta.pivothigh(high,40,40), known 40 bars after the pivot (L375, L388-L390), and the crossover is evaluated BEFORE lsh/lsl are updated on that bar. The score sniper_bull (L625) adds 1 point each for: trend_bull = close>EMA50 and EMA50>EMA200 (L179); upt, which the BOS has already set true (L400-L401); zone_bull = close inside, inclusive, any of the last 3 bullish OBs or last 4 bullish FVGs still in the arrays (L594-L622); and mom_bull = RSI(14)>55 and close>close[5] (L584-L586). Short mirrors this: bos_bear = crossunder(close, lsl), trend_bear, not upt, zone_bear, and RSI<45 with close<close[5] (L626, L629). The implied entry is the signal close, because the TP is computed from close (L646, L660). In the lab it is a market order at the next bar's open. Alerts at L836-L837.
- **Stop:** Long: sl = (lsl if not na else the signal bar's low) − 0.5 × ATR(14) at the signal bar (L645). lsl is the most recent confirmed 40/40 pivot low, wherever it sits. Short: sl = (lsh or high) + 0.5 × ATR (L659). The stop is fixed and never moved. The script does not check that the stop is on the correct side of entry.
- **Target / exit:** Long TP = close + 2 × (close − sl) (L646); short TP = close − 2 × (sl − close) (L660). Fixed 2R measured from the signal close. There are no partials, no time exit and no other exit. The SL/TP lines extend only 20 bars (L650-L653, L664-L667), and nothing detects when they are hit.
- **Position rules:** The script has none. It keeps no position state: each new signal just deletes and replaces the previous label and lines (L636-L667). Same-direction and opposite signals can fire while an earlier one is unresolved. Swing levels are never consumed, so close chopping around the same lsh/lsl produces repeated BOS bars and repeated signals. There is no limit per day, no cooldown, no session window and no end-of-day or weekend flatten.
- **Timeframes:** Chart timeframe only; no HTF in the signal path. The script specifies no timeframe.
- **Sessions (New York):** None (24h).
- **Defaults:** sniper_on true, Min Score 3 (L11-L12). bos_on true, Swing Length 40 (L87-L88). ob_on true, OB Pivot Lookback 10, Max OBs 3 (L79-L81). fvg_on true, Max FVGs 4 (L18-L19). ATR length 14 (L53, used for SL and for OB/FVG invalidation ±0.05 ATR). EMA 50/200, RSI 14 with 55/45 thresholds, ROC 5.

### Breakout channel (EMA100 ± 1.5×ATR14) breakout

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. bull_bo = ta.crossover(close, EMA(close,100) + 1.5×ATR(14)) and bear_bo = ta.crossunder(close, EMA100 − 1.5×ATR) (L140-L145). They set the sticky ch_state (L147-L151), which feeds only the confluence score. 'BO' labels at L160-L169, alerts at L828-L829.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable.
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** Length 100, ATR Multiplier 1.5, ATR Length 14.

### BOS / CHoCH on 40/40 swings

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. bos_bull and bos_bear as defined above (L395-L396). CHoCH = a BOS against the current upt state (L397-L398). Alerts at L830-L833.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable. Levels are never consumed.
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** Swing Length 40.

### 20-bar liquidity sweep

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. sw_hi_c: high > highest(high,20)[1] + 0.15×ATR and close < highest(high,20)[1]. sw_lo_c mirrors it (L434-L438). Labels at L441-L450, alerts at L834-L835.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable.
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** Lookback 20, tolerance 0.15 (an ATR multiple, despite the '%' label).

### High-confluence state (≥4 of 5)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. bull_pts = ch_state==1 + vs_bull (volume buy share >0.55 over 20 bars) + upt + sw_lo_c + close>EMA100. bear_pts is the mirror (L575-L578). The alert condition is c_score >= 4 with bias BULL or BEAR (L838-L839). It is a state, not an event.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Not applicable.
- **Timeframes:** Chart timeframe.
- **Sessions (New York):** None.
- **Defaults:** Volume lookback 20, thresholds 0.55.

### Zones and key levels (S&D, OB, FVG, PDH/PDL, PWH/PWL, NY AM range, Fib golden zone, consolidation boxes)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** No entry. S&D zones use ta.pivothigh/low(10,3) with height 0.4×ATR at the pivot bar (L230-L278). OBs are the body of the pivot candle when it is opposite-coloured, from (10,10) pivots (L283-L327). FVGs are the strict 3-bar gap (L334-L370). PDH/PDL and PWH/PWL come from chart bars via timeframe.change('D'/'W') (L481-L507). The AM high/low covers bars opening 09:30-10:00 NY inclusive (L509-L529). The Fib 0.618-0.786 zone is drawn on the last bar only (L457-L476). Consolidation boxes mark ATR/SMA(ATR,20) < 0.7 for ≥6 bars (L197-L225).
- **Stop:** None.
- **Target / exit:** None. Zones are deleted on a close beyond the far edge ± 0.1 ATR (S&D) or ± 0.05 ATR (OB/FVG).
- **Position rules:** Not applicable. FIFO caps: S&D 4, OB 3, FVG 4 per side.
- **Timeframes:** Chart timeframe, plus day/week boundaries.
- **Sessions (New York):** AM range 09:30-10:00 NY by bar open time, and it includes the bar that opens at 10:00. The other levels follow the symbol's TradingView day/week boundary.
- **Defaults:** sd_left 10, sd_right 3, zone 0.4 ATR; ob_len 10; fvg_max 4; vs_ratio 0.70, vs_min 6.

## Data needs

Sniper strategy: chart-timeframe OHLC only. It needs no volume, no HTF data and no intrabar data. Warm-up should be ≥600 bars to cover EMA200, RSI/ATR RMA seeding, 81-bar pivot windows and filled OB/FVG FIFO lists. Levels-only parts need bar volume (volume sentiment, which feeds only the confluence score and alert), per-instrument trading-day and week boundaries matching TradingView's session (PDH/PDL and PWH/PWL are built from chart bars, not request.security), and the NY clock for the 09:30-10:00 AM range. The scanner pulls 5 external symbols at 15m via request.security (L699-L706) for display only and can be skipped. Nothing else is external.

## Engine features needed

- Close-confirmed signal leading to a market entry at the next bar's open, with a fixed bracket (SL and TP prices computed on the signal bar)
- An option either to keep the absolute SL/TP or to recompute the 2R target from the actual fill price
- Cancel the entry if the next open is already at or through the SL or TP
- Per-instance position gating, i.e. ignoring new signals while a trade is open (the script has none, so this is a user decision)
- Pivot detection with confirmation lag (40/40, 10/10, 10/3)
- Zone registries: FIFO-capped OB/FVG lists, close-based invalidation using the current bar's ATR, and inclusive containment tests
- Exact TradingView ta.ema, ta.rsi, ta.atr (RMA) and ta.crossover semantics
- Levels-only: trading-day/week boundaries per instrument and NY-timezone bar-time windows

## Building blocks

- Swing pivots via ta.pivothigh/pivotlow. This script uses three length pairs: BOS 40/40, OB 10/10, S&D 10/3 (asymmetric). The scanner uses 20/20. Do not reuse script 4's 5/5 pivots
- BOS/CHoCH state: the last pivot level is never consumed; the crossover is evaluated before that bar's level update; upt starts true; bull and bear on the same bar leave upt=false
- Order block (script-5 variant): the body (open/close) of the pivot candle itself, only if it is opposite-coloured (bearish for a bullish OB), FIFO 3, deleted on a close below bottom − 0.05×ATR(current). This is not the same as script 4's LuxAlgo volume-pivot OB
- FVG (script-5 variant): strict 3-bar gap, high[2] < low[0] for bullish, no minimum size, FIFO 4, deleted only on a close beyond the far edge − 0.05×ATR. Partial fills do not invalidate it
- Zone containment: close inside any active box, with inclusive bounds
- Trend filter: close > EMA50 > EMA200
- Momentum: RSI(14) > 55 and close > close[5] (mirror < 45 and <)
- Keltner-style channel: EMA100 ± 1.5×ATR14 with crossover breakouts and a sticky state
- Liquidity sweep (script-5 variant): prior 20-bar highest/lowest ± 0.15×ATR, close back inside, label only
- Volume sentiment: buy/sell split that double-counts volume (L187-L188), 20-bar sums, 0.55 thresholds
- ATR-ratio consolidation detector (ATR/SMA(ATR,20) < 0.7, ≥6 bars)
- Supply/demand zones from (10,3) pivots, height 0.4×ATR at the pivot bar, deleted on a close beyond ± 0.1×ATR
- Key levels from chart bars: PDH/PDL and PWH/PWL via timeframe.change, NY AM 09:30-10:00 high/low
- Fib golden zone 0.618-0.786 of lsh-lsl, last bar only

## Parity risks

- The SL is a level and the TP is derived from the signal-bar close (L645-L646), but the lab fills at the next open. Realised R differs from what the TradingView label implies unless the absolute levels are kept, and a gap can open beyond the SL or TP
- ta.crossover(close, lsh) runs before lsh is reassigned (L385 vs L389). TradingView built-ins keep their own history of the argument as passed at each call, so the [1] side is lsh as it stood before the previous bar's update. On the bar after a new pivot confirms, a port that uses the variable's end-of-bar history gives different BOS bars. Verify against TradingView on bars right after a pivot confirmation
- Pivot tie-handling (equal highs/lows) in ta.pivothigh/pivotlow must match TradingView for all three length pairs
- History-start dependence: upt starts true (L382), lsh/lsl start na (the SL falls back to the bar low), and the OB/FVG FIFO lists fill from the first bar. TradingView's limited intraday history means the lab needs a long warm-up before comparing signals
- Warm-up of EMA200 and the RMA-based RSI/ATR. TradingView seeding conventions must be matched or allowed to converge
- No barstate.isconfirmed gating: on the realtime bar the sniper label/lines and alertconditions can appear and vanish intrabar, depending on the frequency the user picked for the alert. Only close-confirmed historical signals are comparable
- Zone invalidation uses the CURRENT bar's ATR (L319, L325, L362, L368), not the ATR at creation. Containment is inclusive (>=, <=) while crossovers are strict
- Display toggles change signals: fvg_on ('Show Fair Value Gaps'), ob_on and bos_on alter the sniper score or disable it. The port must mirror the user's actual TradingView settings
- PDH/PDL, PWH/PWL and AM come from chart bars, and their boundaries come from TradingView's per-symbol session (CME 18:00 ET, OANDA FX 17:00 ET, crypto 00:00 UTC). The AM window uses bar open time and depends on the chart timeframe. Levels only
- Volume sentiment and the high-confluence alert depend on the volume feed (tick volume for CFD/FX). The sniper does not
- The scanner uses request.security(…, lookahead_off) with no [1], so it repaints in realtime. Display only. The Fib zone and the dashboard exist on the last bar only

## Behaviour found in the code

- Wrong-side or stale stop (L645, L659). The SL uses the latest confirmed 40/40 pivot regardless of where it is. After a fast reversal, before new pivots confirm, lsl can sit above a long's entry (or lsh below a short's). The label then shows SL above entry and TP below it. Every valid stop can also be very far away. There is no guard.
- Swing levels are never consumed (L385-L396). Close oscillating around the same lsh/lsl re-triggers BOS/CHoCH, and therefore sniper signals, repeatedly, with no cooldown.
- Display toggles change trading logic. 'Show Fair Value Gaps' (fvg_on, L18) removes FVGs from the sniper zone point; ob_on removes OBs; bos_on=false disables sniper signals entirely. Zone checks also see only the FIFO-capped last 3 OBs and last 4 FVGs (L294, L341).
- A bullish OB exists only if the pivot-low candle itself is bearish, and a bearish OB only if the pivot-high candle is bullish (L293, L306). There is no search for the last opposite candle, so many pivots produce no OB.
- The scanner (L674-L697) computes a bullish-only score, so READY never reflects shorts. It also uses 20/20 pivots and a volume ratio instead of zones, and requests 15m data with lookahead_off and no offset (repaints in realtime). Its READY is therefore not the chart's sniper condition.
- Volume sentiment double-counts volume (L187-L188). On an up candle buy = full volume and sell is still a fraction of it, so buy+sell > volume. This biases buy_pct, which feeds the confluence score and the high-confluence alert.
- Liquidity 'Tolerance (ATR %)' (L107) is applied as a plain ATR multiple, 0.15×ATR (L436), not a percentage.
- The current-week low label reads 'SL' (L569), a typo for 'WL', which could be mistaken for a stop-loss level.
- The AM range (L514-L516) includes the bar that opens at 10:00, so it actually spans 09:30-10:05 on 5m and 09:30-10:15 on 15m. On hour-aligned 1H charts it captures only the 10:00-11:00 bar.
- The dashboard 'SETUP LONG 3/4' (L631-L633) is a score state that ignores the BOS requirement. It is not the entry signal and can show LONG with no signal.
- Sniper signals ignore ch_state, volume sentiment, sweeps and S&D zones. Those modules feed only the confluence row/alert or are visual.

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| partly | 5.1 Sniper long: on a BOS bar (close crosses over the last 40-bar swing high) when sniper_bull >= 3 of 4 (trend close>EMA50>EMA200, structure up, close inside a bullish OB or FVG, RSI>55 and close>close[5]); entry at close; stop = last swing low - 0.5 ATR; target 2R; shorts mirror. | The scoring, 2R target and mirror are right. Details the claim gets loose: 'last 40-bar swing high' means the most recent ta.pivothigh with 40 bars on BOTH sides, confirmed 40 bars late; it is not the highest high of the last 40 bars, and the level is never consumed, so it can be re-broken repeatedly. 'Bullish OB' is the body of a bearish (10,10) pivot-low candle, and only the last 3 OBs and last 4 FVGs are checked, with inclusive bounds. The stop uses the signal bar's low when no pivot low exists yet. The script never checks that the stop is below entry. Entry at close is only implied, since the label shows only SL and TP and the lab fills at the next open. |
| confirmed | 5.2 Because upt is set to true by the BOS before the score is computed, the structure point always passes on the entry bar, so a signal effectively needs 2 of the other 3. | L400-L401 set upt := true on bos_bull before sniper_bull is computed at L625, and likewise for bear at L402-L403 and L626. The only exception is a bar with both bos_bull and bos_bear: L403 then leaves upt=false. That requires close > lsh and close < lsl at once, which is only possible when a stale lsl sits above lsh. With the default sniper_min 3, that leaves 2 of trend/zone/momentum. |
| partly | 5.3 The zone check will rarely pass at the moment price breaks a swing high, so most signals come from trend + momentum. | The structural argument holds for fresh breaks: FVGs from the BOS bar or the bar before can never qualify. But the zone point can pass, and is most likely to, when price re-breaks an un-consumed swing level from inside an older unmitigated FVG or OB, which is a common pattern because levels are never consumed. How often this happens has not been measured and should be checked on data before stating 'most signals come from trend + momentum'. |
| confirmed | 5.4 The script does not track trades; a new signal only replaces the labels. | L636-L667: the var entry_lbl, sl_line and tp_line are deleted and recreated on each sniper_long/short. There are no strategy.* calls, no position variables and no SL/TP hit detection anywhere (it is an indicator, L4). An opposite signal also replaces them. The lines extend only 20 bars, and on TradingView only the latest signal's SL/TP is visible. |
| partly | 5.5 The high-confluence alerts fire on every bar while the condition holds (a state, not an event). | The condition is indeed a state with no edge detection. But alertcondition does not set its own frequency. It notifies on every bar only if the user's alert is set to 'Once Per Bar' or 'Once Per Bar Close'. With 'Only Once' it fires once and stops. With 'Once Per Bar' it can also fire intrabar on a condition that is false by the close, because there is no barstate.isconfirmed gating. |

## Questions this script raises

- **The script's SL/TP come from the signal-bar close, but the lab fills at the next open. Which prices should the lab use?** Options: Keep the script's absolute SL and TP prices; Keep the SL and recompute TP = fill ± 2×|fill − SL|; Keep both, as two variants. Recommended: Keep the script's absolute SL and TP, and cancel the entry if the next open is already at or through either level — Absolute levels reproduce exactly what the user sees on TradingView. Cancelling avoids instant fills at the target or stop after a gap.
- **The script does not track trades. What should happen to signals that fire while a trade is open, same direction or opposite?** Options: Ignore all new signals until SL/TP; Replace: close the open trade and take the new signal; Reverse only on an opposite signal. Recommended: One position per instance; ignore new signals until the SL or TP is hit — Un-consumed swing levels make repeated signals common. Ignoring them is the least invented rule and keeps the metrics clean.
- **lsl is the latest confirmed 40/40 pivot low wherever it sits, so the long SL can be extremely far away or even above entry (and the reverse for shorts). How should that be handled?** Options: Skip the signal when the SL is on the wrong side of entry; Fall back to signal-bar low/high ∓ 0.5×ATR; Take it as-is. Recommended: Skip the signal when the SL is on the wrong side of entry; otherwise take it as-is and log the risk distance — A wrong-side stop is not a valid trade, and the lab requires a valid stop. Far but valid stops are what the script intends.
- **Which chart timeframe(s) should the sniper run on? The script specifies none.** Options: 5m; 15m; 1H; 15m primary + 5m variant. Recommended: 15m primary plus a 5m variant, on all listed instruments — 40/40 pivots need 40 bars of confirmation (10h on 15m, 3h20m on 5m). 15m matches the user's confirmation timeframe and 5m their entry timeframe.
- **Which Min Score variants should run?** Options: 3 only (default); 3 and 4 as separate instances. Recommended: 3 and 4 as separate instances — On a BOS bar the structure point always passes, so Min Score 3 needs 2 of trend/zone/momentum and Min Score 4 needs all three. That is a meaningfully different filter, and it is a settings variant rather than a new rule.
- **Should open trades be held through session close and weekends?** Options: Hold (faithful); Flatten at the instrument's session close. Recommended: Hold (faithful) — The script has no time exit. Flattening would add a rule the user did not specify.

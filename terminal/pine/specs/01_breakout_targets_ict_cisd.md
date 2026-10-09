# Script 1 · Breakout Targets + ICT Levels + CISD (BT+ICT)

Source: [`../received/01_breakout_targets_ict_cisd.pine`](../received/01_breakout_targets_ict_cisd.pine). Kind: **mixed**. Port complexity: **L** — The main model needs stateful run, consumption and sweep semantics across seven level sources: D/W/M from feed-specific sessions, three NY sessions, and the latest pivot. It also needs two-leg partial exits, replace-on-signal handling, and at least two entry variants because the script's entry price is ambiguous. The scanner variant adds 4-timeframe closed-bar alignment and the A+ bias. Parity checking needs TradingView exports per instrument because the day/week/month boundaries are feed-dependent.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### ICT CISD after liquidity sweep (main chart model)

*Fully defined by the script (entry, stop and exit):* **yes**

- **Entry:** Evaluated on every bar, with no barstate.isconfirmed gate. BEARISH: an up-close run is a series of close>open candles. bullRunOpen is the open of the run's first candle (L640-643). The signal fires when bar_index > bullRunX and close < bullRunOpen (L660) AND |close-open| >= 0.3*nz(ta.atr(14)) (L631, L194) AND a buy-side sweep happened on this bar or within the previous 12 bars (bar_index - lastBslBar <= 12, L661) AND the bar is inside sigWindow (L674-683, default 'Any time') AND showCisd. Buy-side sweep (L614): either high > the latest unswept 5/5 pivot high, or tookHigh() (high > L and high[1] <= L, L585) of PDH/PWH/PMH (request.security D/W/M, L400-402) or of the last completed Asia/London/NY AM high (L595-600). BULLISH mirrors this with the down-close run open, a sell-side sweep (L615) and L667-668. Bear is evaluated first and blocks a bull signal on the same bar (L667). The displayed Entry is the CISD level, i.e. the run open (L732). The signal candle has already closed beyond it: below it for shorts, above it for longs. The script places no order and never checks that price comes back to the level. Its tracker treats the trade as live from the signal bar (L731) and evaluates from the next bar (L751). Order type is therefore undefined; see decisions.
- **Stop:** Bear: bullRunHigh, the highest high from the first candle of the most recent up-close run through the CISD bar inclusive. The extreme is updated on every bar until the run is consumed, and the update runs before the CISD check (L643-645, L663, L733). Bull: bearRunLow, the lowest low over the same span (L650-652, L670). No buffer. The stop is fixed: never trailed, never moved to break-even. R > 0 by construction because the run's first candle has close > open.
- **Target / exit:** R = |entry - stop| (L734). TP1 = entry +/- 1.0R, TP2 = entry +/- 2.0R (L735-736). Checks start on the bar after the signal and are touch-based (>= / <=). If one bar touches both, the stop is assumed hit first (L753). A TP2 touch also marks TP1 (L755). The trade ends at SL, at TP2, at TP1 when TP2 is disabled, or after 4500 bars (L764). After TP1 the stop stays at the original level, so 'TP1 hit then SL' is possible. The script does not say how the position is split between TP1 and TP2.
- **Position rules:** Only one tracked trade exists. Any new CISD in either direction immediately overwrites the live trade (L721-738). The old trade gets no exit price. No max trades per day, no cooldown, no flatten at window or session end: sigWindow only gates signal creation (L674-683). A run's CISD level is consumed (set to na) on ANY close through it, even when the body, sweep or window filter fails (L665, L672; the window filter is applied afterwards at L682-683). A later, stronger close through the same level therefore cannot signal until a new opposing run starts.
- **Timeframes:** Works on any chart timeframe. It was designed on MNQ 5m (L10). Session sweep levels and the window filter only apply on intraday timeframes <= 60m (showSess, L388, L595-600, L680). D/W/M sweep levels apply on every timeframe. The tooltip suggests raising minBody on 1m (L89-90). User plan: 5m entries.
- **Sessions (New York):** Sweep sessions are inputs with tz America/New_York (L58): Asia 20:00-00:00 (L67), London 02:00-05:00 (L69), NY AM 09:30-12:00 (L71). A session level is used only while price is OUTSIDE that session, i.e. the last completed occurrence (L595-600). So before 09:30 the previous day's NY AM high/low is live. NY PM (13:30-16:00, L73) is never a sweep level. Signal window (L86) defaults to 'Any time'. Options: NY AM; NY AM + NY PM; London + NY AM; London + NY AM + NY PM.
- **Defaults:** reqSweep=true, sweepLook=12, minBody=0.3 x ta.atr(14) with nz -> 0 during warm-up, pvL=pvR=5, tp1R=1.0, tp2R=2.0, sigWindow='Any time', showCisd=true, showTrade=true. PDH/PDL, PWH/PWL and PMH/PML sweeps are always active whatever the display toggles say; showPW=false only hides the drawing. Asia, London and NY AM sweep levels also ignore showAsia/showLon/showNYAM.

### Scanner CISD per slot timeframe (3/3-pivot sweep model) with A+ higher-timeframe bias grade

*Fully defined by the script (entry, stop and exit):* **yes**

- **Entry:** scanCisd (L778-872) runs inside request.security for each slot timeframe. BEAR: the latest 3/3 pivot high is swept (high > swH, L801-803; only pivot sweeps, no PDH/PW/PM/session levels) within 12 slot bars (L830), close < the open of the latest up-close run (L829), and |close-open| >= 0.3*ATR14 of the slot timeframe (L825). Entry = run open uOpen (L832). BULL mirrors it (L835-840). No session window. A+ (L902-911): the slot's latest signal direction equals the bias of EVERY enabled higher-timeframe slot, with at least one such slot. Bias = the last swing break, i.e. a close beyond the last 3/3 pivot high or low (L789-800). For higher-timeframe slots the signal reaches the chart one slot bar late via [1]+lookahead_on (L876-877).
- **Stop:** uHigh (short) / dLow (long): the run extreme from the run's first candle through the signal bar (L814-823, L833, L839). Fixed.
- **Target / exit:** TP1/TP2 = entry +/- 1R/2R (L856-857). Status order: stop checked first (L865), then TP2 (L867), then TP1 (L869). Tracking continues after TP1 until TP2 or SL (L861). Status 3 = TP1 then SL. No break-even move, no sizing rule.
- **Position rules:** The latest signal overwrites the slot's trade (L851-860). No caps or cooldowns. alert() fires once per bar on a new signal (L918-931; scanAlerts=true, aplusOnly=false by default). The scanner does NOT filter or alter the main-chart CISD.
- **Timeframes:** Slots 5 / 15 / 60 / 240, all on by default (L101-108). With the defaults, A+ is possible only for the 5, 15 and 60 slots: the 240 slot has no higher slot.
- **Sessions (New York):** None (no session levels, no window).
- **Defaults:** Pivots 3/3 hard-coded (L779-780) and ATR 14 on the slot timeframe. Shares minBody 0.3, reqSweep true, sweepLook 12, tp1R 1, tp2R 2 with the main model. scanAlerts=true, aplusOnly=false.

### Range breakout with measured-move targets

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Signal only: close > ta.highest(high,26)[1] (bull) or close < ta.lowest(low,26)[1] (bear), i.e. the range of the previous 26 bars excluding the current bar (L334-335, L348-349). A new same-direction breakout needs bar_index - lastBrk > 26 (L348-349). It only computes when the chart timeframe is >= minBrkTF, default 60 minutes (L33, L345), so it is OFF on 1m/5m/15m charts. maxRngPct=0 means no range-height filter (L36, L347). Output is a plotshape flag and an alertcondition (L991-995). No entry price or order type is defined.
- **Stop:** None defined. The opposite range edge is drawn as a dotted line (L368) but is never treated as a stop.
- **Target / exit:** T1/T2/T3 = broken edge +/- {0.5, 1.0, 1.618} x (rngHi - rngLo) (L38-40, L359-376). Hits are never tracked and there is no exit logic.
- **Position rules:** None. A new breakout clears the previous drawing (L356-357).
- **Timeframes:** Chart timeframe >= 60m by default (designed on BTC 1W, L6).
- **Sessions (New York):** None.
- **Defaults:** rngLen=26, t1=0.5, t2=1.0, t3=1.618, minBrkTF='60', maxRngPct=0.

### Auto-trendline break

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Signal only: close crosses the descending line, anchored at the highest recent 5/5 pivot high and drawn through a later lower pivot high (L266-281, L315-322), or the ascending mirror (L283-298, L323-330). It fires only while a line is live. Output is a label and an alertcondition (L996-997).
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** None.
- **Timeframes:** Any.
- **Sessions (New York):** None.
- **Defaults:** pvL=pvR=5, showTL=true.

## Data needs

Chart-timeframe OHLC (5m primary; 1m/15m/60m optional) with bar OPEN timestamps convertible to America/New_York with DST. Previous-period high/low for D, W and M, computed with the TradingView daily/weekly/monthly session boundaries of the exact symbol and feed the user charts: CME futures 18:00 ET day; FX, metals and index CFDs usually 17:00 ET depending on broker; crypto 00:00 UTC; weekly and monthly anchors likewise. At least one full prior month of history is needed. Scanner variant: 5/15/60/240 bars anchored like TradingView (for example CME 4H at 18/22/02/06/10/14 ET, FX 4H from 17:00 ET, crypto from 00:00 UTC), with only CLOSED higher-timeframe bars visible. Range breakout: chart timeframe >= 60m. No volume. No lower-timeframe intrabar arrays, except that a scanner slot below the chart timeframe returns only its last intrabar value. Nothing external.

## Engine features needed

- Bar-close signal evaluation with market entry at the next bar's open (one entry variant)
- Resting limit entry at a signal-defined price (the CISD level) with N-bar expiry, plus optional cancel-if-TP1-trades-before-fill (other entry variant)
- Two-leg partial exits (TP1 and TP2) on one position with the stop left unchanged after TP1
- Replace-on-new-signal: flatten at next open and enter the new CISD (stop-and-reverse when the direction is opposite); the lab's MOVE_SL never widens, so a replace must be exit plus re-entry, not a stop edit
- Previous D/W/M high/low from higher-timeframe bars aligned without lookahead (TradingView [1]+lookahead_on semantics: the value of the last HTF bar closed at or before the chart bar's OPEN time)
- Per-instrument exchange-session definitions for day/week/month boundaries in the instrument catalog
- NY-time session membership with DST, including a session that ends at midnight (Asia 20:00-00:00)
- Optional signal-window gating by NY session combinations (London / NY AM / NY PM)
- Pine-equivalent ta.atr(14) (RMA) with the nz(atr)=0 warm-up behaviour
- Pine-equivalent ta.pivothigh/pivotlow (5/5 main, 3/3 scanner) with confirmation delay and Pine tie handling
- Multi-timeframe bars (5/15/60/240) with closed-bar-only alignment, for the scanner/A+ variant only
- No trailing stop, no time-based flatten, no volume required

## Building blocks

- ATR(14): Pine ta.atr (Wilder RMA). The body filter uses nz(atr), so it passes everything for the first ~14 bars
- Pivot high/low: 5/5 in the main model. Only the LATEST pivot per side is kept, and it is cleared by ANY same-side sweep (L588-593, L621, L624). The scanner uses 3/3 with its own swH/swL, cleared only by its own pivot sweep (L789-806)
- Level trade-through 'sweep' (script-1 variant): high > L and high[1] <= L, with no close-back or rejection requirement (L585-586). Levels are never retired, so re-crosses count again
- Previous day/week/month high/low via request.security with [1] + lookahead_on (L400-402)
- Session high/low tracker: reset on the first in-session bar, then running max/min; the value persists until the next session starts and is used as a level only while outside the session (L477-537, L595-600). Session strings have no day mask (Pine default applies)
- CISD run tracker (script-1 variant): the open of the first candle of the latest opposing-close run; the extreme is updated on every bar until consumed; consumed on any close-through even if filters fail; a doji (close == open) breaks a run (L629-672)
- Candle body filter |close-open| >= k x ATR
- Swing-break bias (scanner only): close beyond the last 3/3 pivot sets bias +1/-1 (L795-800)
- Range breakout: highest/lowest of the previous N bars, close-based trigger, same-direction N-bar cooldown, measured targets from the broken edge (L334-376); display/alert only
- Auto trendlines from 5/5 pivots and rejection-block zones (pivot wick to body, min height 0.15 ATR; L200-247, L252-331); display only
- DO (exchange-day open), TDO (exact 00:00 NY bar), 09:30 and 10:00 opens (L444-474); display only, never sweep levels

## Parity risks

- ENTRY PRICE: the script's Entry is the CISD level, which the signal candle has already closed beyond. The tracker never checks a fill and counts SL/TP touches from the next bar. With a body >= 0.3 ATR the close is often already beyond TP1, so a next-open market fill using the script's absolute targets can start with a target behind price. The lab's 'bar opening beyond target fills at open' rule then gives near-zero or negative 'wins'. A limit at the level misses trades that TradingView shows as finished
- Outcome-rule mismatch: the TradingView tracker counts a TP on a touch. The lab requires the close to be beyond the target after an intrabar (limit) fill, and fills at the open on gaps. TP/SL classifications can differ on the fill bar
- Realtime repaint: nothing is gated by barstate.isconfirmed (verified by search). CISD triangles, lines, the trade projection and alertconditions (L989-1002) recompute every tick and can appear and then vanish before the close. Historical bars are stable
- D/W/M levels via request.security [1]+lookahead_on (L400-402) do not repaint, but they depend on the TradingView symbol's session (CME 18:00 ET, FX/CFD 17:00 ET, crypto 00:00 UTC, which shifts in NY time with DST). The synthetic feed and aggregator must reproduce these boundaries per instrument or the PDH/PWH/PMH sweeps will differ
- HTF alignment: on the last chart bar of a higher-timeframe period, TradingView still returns the PREVIOUS HTF bar (the [1] offset is evaluated at bar open). Evaluating at the chart bar's close against an HTF bar that closed at the same instant would use fresher data than TradingView. This affects the PD/PW/PM levels and the scanner A+ bias
- Session membership uses time(timeframe.period, sess, tz) on the bar open time with no day mask. Bars that straddle session edges (for example 1H futures bars at 09:00 vs the 09:30 NY AM start), weekend Asia sessions on 24/7 crypto, and the '2000-0000' midnight end must be matched to TradingView behaviour
- On charts > 60m, session sweep levels are silently disabled and sigWindow is ignored (L388, L680). The same instance on 1H vs 4H behaves differently
- Consumption semantics: a close-through that fails the body, sweep or window filter still consumes the run level (L665, L672). A port that consumes only on valid signals will produce extra signals
- The stop and the CISD level come from the MOST RECENT opposing run. A new single-candle opposing run after the sweep resets both (L640-643). A port that anchors the stop to the sweep bar will differ
- Pine ta.pivothigh/pivotlow tie handling and warm-up (na until 5+5 bars), ta.atr seeding, and nz(atr)=0 on early bars must be replicated
- Scanner: higher slots use [1]+lookahead_on (non-repainting). Slots at or below the chart timeframe use lookahead_off with no offset and update intrabar. A lower-timeframe slot exposes only the last intrabar per chart bar, so earlier signals inside a chart bar collapse into the latest one. alert() uses freq_once_per_bar and can fire on unconfirmed same-timeframe signals
- Back-dated drawings: the CISD line starts at the run start, and zones/trendlines are drawn at bar_index-pvR. They use only known information, but visual comparison against TradingView must use the signal bar, not the line start
- The tracker drops a live trade when any new CISD prints (L721). TradingView's visible TP/SL marks therefore cover only the latest trade; earlier trades have no recorded outcome to compare against

## Behaviour found in the code

- A failed filter still consumes the CISD level. When a close crosses a run's open but fails minBody, the sweep recency, or (applied later, L682-683) the session window, the level is still set to na (L665, L672). A stronger close through the same level a bar later produces no signal.
- The stop and CISD level reset with every new opposing run (L640-643, L647-650). After a sweep, a single small opposing candle restarts the run, so the stop can sit well inside the sweep wick. This is not 'the extreme of the sweep'.
- Sweep levels ignore the display toggles. PWH/PWL (showPW=false, L64) and PMH/PML are always swept (L603-604, L608-609). Asia, London and NY AM sweeps ignore showAsia/showLon/showNYAM. Hiding a level on the chart does not remove it from the signal logic.
- The tracker's 'Entry' is never verified (L751). It reports TP/SL outcomes as if filled at the CISD level even if price never returns there. Because of the >= 0.3 ATR body, TP1 is often already behind the signal close.
- Any new CISD silently replaces the live projected trade, with no exit (L721). Earlier trades lose their outcome on the chart.
- The range breakout is gated to charts >= 60m by default (L33, L345), so it never appears on 1m/5m/15m charts.
- The scanner comment calls it a 'self-contained copy of the CISD model' (L775-776), but it is a different model (3/3 pivots, pivot-only sweeps, no session levels or window). Its A+ badge can attach to a stale or finished signal, because d is the last signal direction kept forever (L843-860, L900).
- Session sweep levels and the signal window are disabled on charts > 60m (L388, L680). The session strings have no day mask, so weekend behaviour on 24/7 crypto follows Pine's default.
- nz(atr) makes the body filter accept every candle during the first ~14 bars (L631).
- Session levels are never retired once swept (L585-586, L595-600). The same Asia, London or PDH level can register a new 'sweep' each time price dips back below it and re-crosses, keeping the 12-bar recency flag alive.

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| partly | 1.1 The tradable setup is a CISD after a liquidity sweep of PDH/PDL, PWH/PWL, PMH/PML, Asia (20:00-00:00 NY), London (02:00-05:00), NY AM (09:30-12:00) highs/lows or 5/5 pivots; min body 0.3 x ATR; sweep lookback 12 bars. | The sweep is direction-paired: a bearish CISD needs a buy-side sweep (highs taken) and a bullish CISD needs a sell-side sweep. A 'sweep' is only a trade-through (high > level with prior high <= level; for pivots, high > the latest pivot), with no close-back requirement. Only the most recent 5/5 pivot per side counts, and any same-side sweep clears it. Session levels count only outside their own session (the last completed occurrence, so yesterday's NY AM high/low before 09:30) and only on charts <= 60m. NY PM is never a sweep level. PWH/PWL count even though PW is hidden by default. The sweep may be on the CISD bar itself or up to 12 bars before it. The body filter is \|close-open\| >= 0.3 x ta.atr(14) and is disabled during ATR warm-up. There is no session restriction by default. |
| partly | 1.2 Entry is at the CISD level, stop at the extreme of the run that made the sweep, TP1 = 1R and TP2 = 2R. | The Entry label is the CISD level, but the signal candle has already closed beyond it. The script places no order and treats the trade as filled at the signal bar. The stop is the highest high (short) or lowest low (long) from the first candle of the MOST RECENT opposing-close run through the CISD bar. That run need not be the one that made the sweep: if a new small opposing run starts after the sweep, the stop can sit inside the sweep wick. TP1 = 1R and TP2 = 2R is correct, with R = \|entry - stop\|. There is no sizing split and no break-even move. The trade ends at SL, at TP2 (or TP1 if TP2 is disabled), or is replaced by any new CISD. |
| confirmed | 1.3 There is a separate range-breakout feature (range length 26, targets at 0.5 / 1 / 1.618 of the range) which does not define a stop. | L35 rngLen=26. L38-40 t1/t2/t3 = 0.5/1.0/1.618. L359 and L372: target = broken edge +/- r x (rngHi - rngLo). No stop or exit tracking anywhere in L333-386; output is only plotshape/alertcondition (L991-995). Additional facts: the range is the previous 26 bars excluding the current bar (L334-335). The trigger is a close beyond the range with a >26-bar same-direction cooldown (L348-349). It is disabled on charts below 60m by default (L33, L345), so it never shows on the user's 5m/15m charts. The opposite edge is drawn (L368) but not used as a stop. |
| partly | 1.4 There is an MTF scanner on 5/15/60/240 with an 'A+' bias-agreement grade; it is display only. | The slots and the A+ grade exist as stated, but the scanner is not display-only. It fires alert() calls and alertconditions on new slot signals, and it is a separate tradable CISD variant: 3/3 pivots, sweeps only of the latest 3/3 swing, no PDH/PW/PM or session levels, no session window, with its own Entry/SL/TP1/TP2 and status per slot. A+ means the slot's LATEST signal direction (regardless of age or whether that trade has finished) equals the swing-break bias (close beyond the last 3/3 pivot) of every enabled higher slot, with at least one higher slot required. The 240 slot can therefore never be A+. A+ does not filter the main-chart CISD. |
| partly | 1.5 The script draws signals only on confirmed bars / does not repaint its entries (check request.security usage and any lookahead). | There is no lookahead on historical bars, and historical CISD signals are stable. Signals are NOT limited to confirmed bars: on the live bar the CISD markers, CISD line, Entry/SL/TP projection and alertconditions recompute every tick and can appear and then disappear before the close. Scanner slots at or below the chart timeframe show unconfirmed intrabar values, and their alert() calls can fire intrabar. Drawings are back-dated to the run start or the pivot bar, but they use only information available at the signal bar. |

## Questions this script raises

- **How should a CISD signal be entered? The script prints an Entry at the CISD level but places no order and never checks a fill.** Options: Limit order at the CISD level (the script's Entry label), with the script's SL/TP1/TP2, expiring after N bars; Market at the next bar's open, with the script's absolute SL/TP1/TP2 prices; Market at the next bar's open, with the script's SL and TP1/TP2 recomputed as 1R/2R from the actual fill. Recommended: Limit at the CISD level, expiring after 12 bars (reusing the script's 12-bar sweep window), cancelled if TP1 trades before the fill. Run 'market at next open, script levels' as a second instance for comparison. — The signal candle has already closed beyond the level. Only a limit at the level reproduces the entry, stop and target prices the user sees. A market entry with the same targets often finds TP1 already passed.
- **How is the position split between TP1 (1R) and TP2 (2R)?** Options: 50% at TP1 / 50% at TP2, stop unchanged; 100% at TP2; 100% at TP1; 50/50 and move the stop to entry after TP1. Recommended: 50% at TP1 / 50% at TP2, stop unchanged. Add TP1-only and TP2-only variant instances if wanted. — The script defines two targets but no sizing. It never moves the stop after TP1 (L748-765), so a break-even move would be an invention.
- **What happens when a new CISD prints while a trade is open?** Options: Replace: exit at the next open and take the new signal (reverses if opposite); Ignore new signals until flat; Reverse on opposite-direction signals only; ignore same-direction ones. Recommended: Replace (exit at the next open, then enter the new signal). — The script overwrites the live trade on any new CISD (L721) without defining an exit. Replacing is the closest faithful behaviour; the lab cannot widen a stop in place.
- **Which signal windows should run as instances, and should positions be flattened at window or session end?** Options: 'Any time' only (script default); 'Any time' plus 'NY AM' and 'London + NY AM' as separate instances; Add a forced flatten at 16:00 NY (or at window end). Recommended: Three instances: 'Any time', 'NY AM' (09:30-12:00) and 'London + NY AM'. No forced flatten. — The user asked for London and New York session strategies. The script only filters signal creation and never flattens.
- **Which day/week/month boundaries define PDH/PDL, PWH/PWL and PMH/PML for each instrument?** Options: Mirror the exact TradingView symbol/broker the user charts, configured per instrument; Asset-class catalog defaults: CME 18:00 ET, FX/metals/index CFDs 17:00 ET, crypto 00:00 UTC; NY-midnight days for everything. Recommended: Asset-class catalog defaults, confirmed against the user's actual TradingView symbols (for example OANDA vs FX vs Capital.com for XAUUSD and NAS100). — request.security('D'/'W'/'M') follows the symbol's exchange session, which the script does not control. The levels, and therefore the sweeps, change with it.
- **Should the scanner's own CISD model (3/3-pivot sweep only, per slot timeframe, A+ bias grade) be ported as a separate strategy?** Options: Yes, as its own strategy: base instance without A+, plus a variant that requires A+ (5m signal agreeing with the 15/60/240 bias); Yes, base only; No, treat it as display/alerts only. Recommended: Yes, as its own strategy: base instance plus an A+-required variant instance. — The scanner defines entry, stop and TP1/TP2 per slot and differs materially from the main model. A+ is this script's own filter, not a combination with another indicator.
- **Which chart timeframe(s) and body threshold should the main CISD instances use?** Options: 5m with minBody 0.3; 5m plus a 1m instance with a higher minBody (e.g. 0.5); 15m with minBody 0.3. Recommended: 5m with minBody 0.3 (the script's design chart). Add a 1m instance with minBody 0.5 only if wanted. — The script runs on any timeframe. The user enters on 5m, and the tooltip (L89-90) says to raise minBody on 1m but gives no value.
- **Should the range breakout or trendline break be traded?** Options: No, keep them as display/levels only; Yes, with a user-defined stop (e.g. the opposite range edge or the range midpoint). Recommended: No, keep them as levels only. — Neither defines a stop or exit tracking, and the porting rules forbid inventing them. The range breakout is also off below 60m by default.

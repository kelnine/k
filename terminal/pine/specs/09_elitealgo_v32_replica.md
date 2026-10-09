# Script 9 · EliteAlgo v32 pulse ai (replica+) — 09_elitealgo_v32_replica.pine

Source: [`../received/09_elitealgo_v32_replica.pine`](../received/09_elitealgo_v32_replica.pine). Kind: **strategy**. Port complexity: **M** — The trading logic is small: one cross trigger, a counter, a fixed ATR bracket and a cooldown. A parity-checked port, though, needs Pine-exact EMA/RMA/RSI/DMI implementations (the indicators package is empty today) and a daily-anchored VWAP. The VWAP needs per-instrument rollover and a volume source matching TradingView, and that data-side parity cannot be fixed in code.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### EMA 8/21 cross with 4-of-7 confluence, ATR bracket (long and short, shared cooldown)

*Fully defined by the script (entry, stop and exit):* **yes**

- **Entry:** LONG on the close of a bar where all of these hold (L64): ta.crossover(EMA8, EMA21), meaning EMA8 > EMA21 and EMA8[1] <= EMA21[1]; bullCnt >= minConfl (4); trendOKL = close > EMA200 (L61, useTrendF on by default); coolOK = na(lastSigBar) or bar_index - lastSigBar >= 5 (L60); confirmed = barstate.isconfirmed (L58). bullCnt (L53) is one point each for close > EMA200, EMA8 > EMA21, RSI14 > 50, DI+ > DI- from ta.dmi(14,14), pHist > 0 where pHist = (EMA5 - EMA60) - EMA20(EMA5 - EMA60) (L44-45), close > open, and close > ta.vwap(hlc3) (L42). SHORT on the close of a bar with ta.crossunder(EMA8, EMA21) AND bearCnt >= 4 AND close < EMA200 AND coolOK AND confirmed (L65). bearCnt = 7 - bullCnt (L54), so ties and na count as bearish. The script's entry price is the signal-bar close (L95, also in the alert text, L107). Lab: MARKET order filled at the next bar's open, with the signal close as the reference entry.
- **Stop:** Fixed at the signal: risk = ATR(14) of the signal bar x 1.5 (L96). Long SL = signal close - risk; short SL = signal close + risk (L97). It never trails or moves.
- **Target / exit:** Fixed TP at 2R from the signal close (L98). Long TP = close + 2 x risk = close + 3.0 x ATR(14); short TP = close - 3.0 x ATR(14). There is no other exit: no time exit, no session exit, and no exit on an opposite cross. The script itself never checks whether SL or TP were hit (L99-106).
- **Position rules:** The script tracks no position. Every new signal in either direction deletes and redraws the entry/SL/TP lines (L99-106), and the dashboard shows the last signal forever (L144-145). Cooldown: lastSigBar is set on every long OR short signal (L93), so the 4 bars after any signal block all signals in both directions. A crossover blocked by the cooldown, the confluence rule or the trend filter is lost because a cross is a one-bar event; it is not deferred. There is no max trades per day, no session window and no flatten. Port requirements: (a) one strategy covering both directions, because splitting long and short would break the shared cooldown; (b) the cooldown counter must update on every script signal, even one the engine ignores; (c) opposite signal while in a position: the engine default 'reverse' at next open matches the line replacement (decision); (d) same-direction signal while in a position: the engine ignores it (max_pyramiding=1), whereas TradingView would redraw the bracket (decision).
- **Timeframes:** Any single chart timeframe. There is no request.security and no HTF. Proposed instances: 5m and 15m as separate instances (1m and 1H also possible).
- **Sessions (New York):** None: signals fire 24h. The London 08:00-16:30 Europe/London and New York 09:30-16:00 America/New_York windows (L76-78) only feed the dashboard 'Session' text. VWAP resets at the start of each trading day (ta.vwap default anchor = new 1D bar of the symbol's session).
- **Defaults:** fastLen 8, slowLen 21, trndLen 200, rsiLen 14, adxLen 14, adxSm 14, atrLen 14, pulse fast/slow/signal 5/60/20, minConfl 4, useTrendF true, waitClose true, coolBars 5, slMult 1.5, rrRatio 2.0 (L6-24).

## Data needs

Chart-timeframe OHLCV only (any TF; proposed 5m and 15m). Bar VOLUME is required because the 'close > VWAP' check is one of the 7 confluence points. It needs per-instrument trading-day boundaries to reset the VWAP, equivalent to TradingView's timeframe.change('1D') for that symbol. The catalog's trading_day_rules give 17:00 New York (ny_1700) and 00:00 UTC (utc_midnight). It needs no higher timeframe, no daily or weekly bars and no intrabar data. Warm-up: EMA200 must exist (>= 200 bars). >= 1000 bars are recommended so that EMA200 and the Wilder RSI/ATR/DMI converge to TradingView's values.

## Engine features needed

- MARKET entry at the next bar open with a fixed SL/TP bracket at absolute prices computed on the signal bar (exists)
- on_opposite_signal = reverse and max_pyramiding = 1 (exist; behaviour choice is a user decision)
- Strategy-side bar-count cooldown shared by both directions, counted in bar_index (primary bars, not time) and updated on every script signal regardless of position state
- Day-anchored VWAP that resets at each instrument's trading-day rollover from the catalog
- Bar volume in the market-data feed (the synthetic feed must emit volume, and real feeds must say whether it is tick or traded volume)

## Building blocks

- EMA in Pine ta.ema semantics (lengths 8, 21, 200, 5, 60, plus EMA20 of the pulse); warm-up and seeding must match Pine
- RSI(14), Pine ta.rsi (Wilder RMA; 100 when there are no losses)
- ATR(14), Pine ta.atr = RMA of true range (first bar TR = high - low)
- DMI ta.dmi(14, 14): only DI+ vs DI- is used for signals; ADX > 20 is display-only
- VWAP of hlc3, cumulative sum(hlc3 x vol) / sum(vol), reset at the daily session start, no bands. Variant: daily-anchored, chart-TF bars
- 'Pulse' histogram = (EMA5 - EMA60) - EMA20 of that, i.e. a MACD(5,60,20) histogram built on EMA signal smoothing
- crossover / crossunder in Pine semantics (a > b and a[1] <= b[1])
- 7-point confluence counter where the bearish count is the complement (ties and na count bearish)
- Bar-count signal cooldown shared across directions

## Parity risks

- Fill price: TradingView's levels and alert use the signal-bar close (L95-98), while the lab fills at the next open. At session breaks (CME/CFD daily halt, weekends, FX Sunday open) the next open can gap past the SL or TP, so realised R differs from the 2:1 drawn on the chart.
- VWAP anchoring: ta.vwap resets on the symbol's TradingView daily boundary (CME 17:00 CT = 18:00 ET, OANDA-style FX/metals/CFD 17:00 ET, crypto 00:00 UTC). If our anchor differs, the VWAP check flips and confluence counts change.
- VWAP volume: FX/CFD tick volume differs by broker, and crypto volume differs by exchange. If volume is 0 or missing, VWAP is na, so close > vwap is false. That always adds a bearish point and removes a bullish one.
- Ties and na count as bearish (bearCnt = 7 - bullCnt, L54). A Python port that uses symmetric strict comparisons, or NaN, for the bear side will differ.
- EMA/RMA warm-up and seeding must replicate Pine's built-ins (ta.ema, ta.rma inside ta.rsi/ta.atr/ta.dmi). The EMA200 trend filter depends on how much history is loaded, so load >= 1000 warm-up bars and compare against a TradingView export.
- The cooldown counts bars (bar_index). If our aggregator skips or adds bars (gaps, empty synthetic bars, session halts) differently from TradingView, signals blocked or allowed by the cooldown will differ.
- Signals are gated on barstate.isconfirmed (true on all historical bars), so closed-bar evaluation matches TradingView. With waitClose=false they would appear and vanish intrabar, and the alert() with freq_once_per_bar would fire on the first qualifying tick.
- On TradingView the lines never close, so a user eyeballing the chart may count a 'TP hit' that came after the stop. Recorded lab trades (stop first when a bar touches both) will not match visual impressions.
- A same-direction signal while in a trade redraws the bracket on TradingView, but the engine ignores it (max_pyramiding=1). The chart's current lines can then differ from the open lab trade.

## Behaviour found in the code

- Ties and na are biased toward shorts (L53-54). bearCnt is the complement of bullCnt, so dojis (close == open), RSI exactly 50, equal DIs, pulse == 0 and close == VWAP all add a bearish point. On a feed with no volume, ta.vwap is na, so the VWAP check is permanently bearish: longs effectively need 2 of 4 remaining checks while shorts get that point free.
- The cooldown is shared across directions and is signal-based, not trade-based (L60, L93). A valid opposite crossover within 4 bars of a signal is permanently dropped, and the old SL/TP lines stay on the chart even though the EMAs have crossed against them.
- The confidence display can never be 0% and only takes the values 14/43/71/100 (L73), contradicting the comment. biasBull uses '>=' but a tie is impossible with 7 checks (L55).
- 'Market' regime (ADX > 20, ATR% vs SMA100 of ATR%, L47-49, L75) and 'Session' (L76-78) are display-only. They are not filters despite appearing next to the signal on the dashboard.
- Entry, stop and target are computed from the signal-bar close and ATR (L95-98). With next-open fills, entries after a session break or weekend can open beyond the drawn stop or target.
- Two alert paths exist: alert() with freq_once_per_bar (L107), and alertcondition (L148-149) whose message uses {{close}} and has no SL/TP. Which one the user wired to TradingView alerts affects what they observed live.

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| partly | 9.1 Long: EMA 8 crosses above EMA 21, close > EMA 200 (trend filter on by default), and at least 4 of 7 bullish checks; stop = close - 1.5 ATR; target 2R; 5-bar cooldown between signals; shorts mirror. | The long-side numbers are right. ATR is ATR(14) of the signal bar, and stop and target are measured from the signal-bar close (TP = close + 3.0 ATR). Two corrections. (1) The 5-bar cooldown is shared by both directions: a long blocks shorts and longs for the next 4 bars, and a crossover blocked by the cooldown is lost, not delayed. (2) Shorts are not an exact mirror. bearCnt = 7 - bullCnt, so every tie or na counts as bearish: close == open, RSI == 50, DI+ == DI-, pulse == 0, close == VWAP, and a VWAP that is na on a feed without volume. |
| confirmed | 9.2 On the crossover bar 'EMA 8 > EMA 21' is always true and the trend filter already forces 'close > EMA 200', so the 4-of-7 rule is effectively 2 of the other 5. | ta.crossover requires emaF > emaS on the current bar, so the b2i(emaF > emaS) term (L53) is 1. trendOKL = close > emaT is mandatory with useTrendF true (L61, L17), so b2i(close > emaT) is 1. bullCnt >= 4 (L64) therefore needs >= 2 of: RSI>50, DI+>DI-, pHist>0, close>open, close>VWAP. Shorts are the same: crossunder means emaF < emaS (a bear point), and close < emaT (a bear point). With the trend filter off it becomes 3 of the other 6. |
| partly | 9.3 Nothing in the script is AI or learned; confidence/strength/stars are counts of the checks. | 'Nothing AI' is confirmed; the 'pulse ai' title is branding. But strength is not a count: it is the RSI distance from 50, scaled to 0-100. Stars and confidence are count-based. Confidence can only be 14, 43, 71 or 100% because bullCnt + bearCnt = 7 (odd), so the '0% = coin flip' comment on L73 is wrong. The dashboard values are those of the LAST bar, not of the signal bar (L134-146). |
| confirmed | 9.4 Signals are confirmed on bar close by default (waitClose = true). | L18 waitClose default true. L58: confirmed = not waitClose or barstate.isconfirmed. L64-65: both signals AND confirmed. barstate.isconfirmed is true on every historical bar and only on the closing tick of the realtime bar. The script has no request.security, so nothing else repaints. alert() (L107) and alertcondition (L148-149) are driven by the gated signals. |
| confirmed | 9.5 The script does not track trades; a new signal replaces the SL/TP lines. | L82-106: var dir/entryP/slP/tpP are only overwritten on a signal. The old lines are deleted (L99-101) and new extend.right lines are drawn (L103-106). Nothing compares high/low with slP/tpP; it is an indicator() (L2) with no strategy.* calls. Same-direction and opposite signals both replace the lines. Between signals the dashboard keeps showing the last entry/SL/TP (L144-145). |

## Questions this script raises

- **What happens when an opposite signal arrives while a trade is open?** Options: Reverse at next open (engine default); Ignore it until SL/TP is hit; Exit only, no new trade. Recommended: Reverse at next open — The script replaces the bracket on every signal, so the chart's 'current trade' is always the latest signal. Reversing reproduces that, and it is already the engine default.
- **What happens when a same-direction signal arrives while a trade is open?** Options: Ignore (keep the original bracket); Move SL/TP to the new levels, only when that does not widen the stop; Exit and re-enter at next open. Recommended: Ignore (keep the original bracket) — The script redraws the lines but has no position concept. Ignoring is the engine default and avoids churn. The cooldown counter still updates either way.
- **Where are SL/TP anchored, given the lab fills at the next open?** Options: Absolute levels from the signal-bar close, as drawn on TradingView (close +/- 1.5 ATR, TP at 2R from close); Re-based on the actual fill price (fill +/- 1.5 ATR, 2R from fill). Recommended: Absolute levels from the signal-bar close — This matches the lines and alert text the user sees on TradingView. Lab metrics are computed from the actual fill anyway.
- **Which VWAP reset time and volume source applies per instrument?** Options: The catalog trading-day rollover (17:00 New York for FX, metals, CFD indices and CME; 00:00 UTC for crypto) with the feed's bar volume; A different anchor per broker or listing. Recommended: The catalog trading-day rollover with the feed's bar volume. Flag instances whose feed has no volume as non-parity, because their VWAP check is always false. — The script uses the TradingView default daily anchor. The catalog rollover is the closest equivalent we already maintain.
- **Which timeframes should run as instances?** Options: 5m only; 5m and 15m; 1m, 5m, 15m and 1H. Recommended: 5m and 15m as two instances — The script is timeframe-agnostic. These match the user's entry and confirmation timeframes.
- **Should there be any session filter or forced flatten? The script has neither.** Options: None: 24h signals, hold through session breaks and weekends; Flatten at the instrument's session close; Only trade London/NY hours. Recommended: None (faithful port). Add session-filtered variants later as separate instances if wanted. — The session windows in the script are display-only. Adding a filter would no longer be the user's script.

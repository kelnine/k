# Script 8 · FRVP + ORB + 9/20 EMA (08_frvp_orb_ema.pine)

Source: [`../received/08_frvp_orb_ema.pine`](../received/08_frvp_orb_ema.pine). Kind: **mixed**. Port complexity: **S** — About 40 lines of signal logic: one DST-correct NY window (ny_orb_15 already exists in the lab), a per-day OR high/low, two per-direction counters, and an EMA 9/20 filter. The profile is display only and can be skipped. The remaining work is your stop/exit decisions plus a 16:00 flatten. Parity checks are limited to bar-open-time session membership, the stale-OR edge case and EMA warm-up.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### ORB close breakout with EMA 9/20 direction filter (long and short)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Long signal: the first confirmed bar (barstate.isconfirmed, line 150) where all of these hold: (1) the bar OPENS inside lvlSess 09:30-16:00 America/New_York (114, 143); (2) today's OR has formed, i.e. formed was set on the first bar after the OR window, and that same bar can already signal (134-136, 143); (3) close > OR high, strict (151); (4) when orFilter is on, EMA9 > EMA20 strictly on that bar (102, 151); (5) no long has fired yet for this OR day (151, 153). The short mirrors this: close < OR low and EMA9 < EMA20 (154-156). The condition is a level state, not a cross. The OR high/low is the wick high/low of every chart bar that opens in 09:30-09:45 (121-132). The script places no order; the marker and alert sit on the signal bar's close (158-162). In the lab: market entry at the next bar's open.
- **Stop:** None defined. The ORH, ORL and mid lines (137-139) are drawn but are never used as stops.
- **Target / exit:** None defined. Nothing happens at 16:00 except that signals stop and the lines stop extending (143).
- **Position rules:** The script has no position concept. Each OR day allows at most one long signal and one short signal (longDone/shortDone, 55-57, 153, 156). Both can fire on the same day, for example a long at 10:05 and a short at 13:20. A counter is consumed only when its signal actually fires: a breakout blocked by the EMA filter does not count, so a long can fire hours later on the bar where the EMA turns bullish while price is still above ORH. Counters reset at the next day's OR start (121-124). There is no cooldown. If a day has no bar opening in 09:30-09:45, 'cur' still holds the previous day's OR and its unused signals can fire against those stale levels (120-156). All of this sits inside 'if showOR' (120): hiding the OR disables the signals.
- **Timeframes:** Chart timeframe, intraday only (113). The tooltip (30) recommends a timeframe no larger than the OR (1m/2m/5m). 15m works (the OR is the single 09:30 bar). On a 1H chart with bars on the hour, no bar opens in 09:30-09:45, so no OR and no signals; on 09:30-aligned 1H bars, the OR becomes the whole 60-minute bar. The EMAs run on the chart timeframe.
- **Sessions (New York):** OR: 09:30-09:45 America/New_York with DST (9, 30), by bar open time (on 5m: the 09:30, 09:35 and 09:40 bars). Signals: from the first bar after the OR (09:45) through the last bar opening before 16:00 (15:55 on 5m). The session string has no day list, so it applies on every day with bars, crypto weekends included (verify).
- **Defaults:** tz=America/New_York, orSess=0930-0945, lvlSess=0930-1600, orSignals=true, orFilter=true, fastLen=9, slowLen=20 (EMA of close), showOR=true (required for signals), orKeep=3 (display only). Variants: orFilter off; OR 0930-0935 or 0930-1000

### EMA 9/20 cross (alert only)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** alertcondition(ta.crossover(emaFast, emaSlow)) and alertcondition(ta.crossunder(...)) (163-164). Evaluated on every bar and every realtime tick, with no barstate.isconfirmed gate, no session filter and no per-day limit. No marker is plotted.
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None.
- **Timeframes:** Chart timeframe
- **Sessions (New York):** None (24h)
- **Defaults:** fastLen=9, slowLen=20, source=close

## Data needs

Chart-timeframe intraday OHLC with bar-open timestamps converted to America/New_York with DST. 1m or 5m recommended; 15m gives a single-bar OR; 1H is not suitable. EMA(9) and EMA(20) of close on the same timeframe, which needs at least 200 warm-up bars including the overnight bars the user's TradingView chart shows. Volume only for the display-only profile. No HTF, daily or intrabar data.

## Engine features needed

- Session-window membership by bar OPEN time in America/New_York, DST-correct. ny_orb_15 already exists; add a 09:30-16:00 'levels active' window
- Per-day, per-direction one-signal counters, consumed when the signal fires whether or not a position opens, so they mirror TradingView's markers
- Market entry at the next bar's open (existing)
- A stop computed at signal time from the OR levels (user decision); stop_loss is mandatory
- Optional fixed R-multiple target
- Flatten at a clock time (16:00 NY): an EXIT on the last in-window bar, or an engine time exit
- on_opposite_signal policy, ignore vs reverse (existing meta field)
- Optional entry cutoff near the end of the window
- EMA indicator with Pine-compatible warm-up

## Building blocks

- EMA of close, lengths 9 and 20, via ta.ema (Pine seeding; converges after warm-up)
- Session window membership (script-8 variant): time(timeframe.period, sess, 'America/New_York'), half-open [start, end), by bar open time
- Opening range (script-8 variant): wick high/low of all chart bars opening in 09:30-09:45; formed on the first bar after the window; the levels persist until the next day's OR start
- Breakout trigger (script-8 variant): level state close > ORH / close < ORL (strict, not a cross), once per direction per OR day, with the counter consumed only when the EMA filter passes
- Volume profile (script-8 variant, display only): volume spread by the proportion of each bar's range overlapping each row, up/down by close >= open, value area ties going up, POC/VAH/VAL rounded to mintick. Differs from script 7's equal-split profile

## Parity risks

- TradingView shows the signal at the breakout bar's close; the lab fills at the next bar's open. The user will compare against the marker price
- Session membership is by bar open time. The chart timeframe must be 15m or smaller and aligned to 09:30 for a true 15-minute OR. On-the-hour 1H bars never form an OR; 09:30-aligned bars longer than 15m make the OR the whole bar. Confirm that TradingView's time() treats bars that straddle 09:30 the same way the lab does
- Data vendor differences: the user's TradingView CFD or futures feed (NAS100 vs MNQ1!) will have different 09:30-09:45 highs/lows and closes from our feed. A one-tick difference changes which bar breaks out
- EMA values at 09:45 depend on the overnight/pre-market bars present (24h CFDs/futures vs RTH-only charts) and on Pine's EMA seed; use at least 200 warm-up bars on the same session set
- Last eligible signal bar: the bar opening 15:55 on 5m signals at 16:00, and with a next-open fill the entry lands at or after 16:00
- Stale OR: with no bar opening in 09:30-09:45 on a day (data gap or holiday schedule), the previous day's ORDay stays current and its unused long/short can fire during the next day's 09:30-16:00 (120-156)
- Strict > and < against float levels: ties do not signal, so round prices to tick consistently
- The session string has no day list, so ORs form on weekends for 24/7 crypto. The lab must do the same for parity
- The ORB alert fires only on the confirmed tick (150), which matches the lab. The EMA-cross alerts (163-164) can fire intrabar on TradingView
- 'Last N bars' profile mode uses last_bar_index (187), which is look-ahead, but it is display only and irrelevant to signals

## Behaviour found in the code

- The ORB signals live inside 'if showOR' (line 120). Hiding the opening-range drawing also kills the ORB signals and alerts
- The trigger is a level state (close > ORH), not a crossover, and the counter is consumed only when the EMA filter passes. A 'breakout' can therefore be marked on a bar far above the range, hours after the real breakout, on the bar where EMA9 crosses above EMA20
- Stale-OR carry-over: 'cur' is replaced only when a bar opens inside 09:30-09:45 (121). On a day without such a bar, the previous day's levels and any unused long/short signal stay live for that day's 09:30-16:00 bars (143-156)
- Charts whose bars are longer than 15m but aligned to 09:30 make the 'OR' the entire first bar (for example 09:30-10:30 on 1H). On-the-hour 1H bars never form an OR, so the indicator silently shows no signals
- A signal on the 15:55 bar (5m) is allowed. With the lab's next-open fill, the entry would sit at or after 16:00, outside the script's window
- The EMA-cross alerts (163-164) are not confirmation-gated, not session-limited and not plotted
- The profile's 'Last N bars' mode uses last_bar_index (187), which is look-ahead, but it only affects the drawing

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| partly | 8.1 Opening range 09:30-09:45 NY; signal = first candle CLOSE above range high (long) or below range low (short) until 16:00; at most one long and one short per day; EMA 9 > EMA 20 filter for longs (and < for shorts) on by default. | The basics are right, but the signal is not 'the first candle close above the high'. (a) It is the first confirmed close beyond the level that also passes the EMA filter. A filtered-out breakout does not use up the day's signal, and because the test is a state (close > ORH), not a cross, a long can fire hours later on the bar where EMA9 rises above EMA20 while price is still above ORH. (b) The first eligible bar is the bar right after the OR (09:45), since formed is set in the same execution (134-143). (c) 'Until 16:00' means bars that open before 16:00: the last 5m signal bar is 15:55. (d) OR membership is by bar open time, so a true 15-minute OR needs a chart of 15m or smaller aligned to 09:30. (e) Turning off 'Show opening range' (showOR, 120) disables all signals. (f) A long and a short can both fire on the same day. (g) If a day has no OR bars, the previous day's OR and its unused signals carry over. |
| partly | 8.2 Signals are only generated on confirmed (closed) candles; no stop or target is defined. | True for the ORB long/short signals, and no stop or target exists. The EMA 9/20 cross alerts (163-164) are not gated by barstate.isconfirmed and can trigger intrabar on live bars, depending on the alert frequency setting. |
| confirmed | 8.3 The volume profile is display only. | Profile bars are accumulated at 181-195 and the profile is computed and drawn only inside 'if barstate.islast' (203-305). POC/VAH/VAL (262-264) are local to that block: they are not plotted, not used by any signal (143-156) and not referenced by any alertcondition (161-164). It is independent of the ORB and the EMAs. |

## Questions this script raises

- **Where should the stop go? The script defines none, and the lab requires one.** Options: Opposite side of the opening range; OR midpoint; Breakout bar's low (long) / high (short); ATR multiple from entry. Recommended: Opposite side of the opening range (OR midpoint as a variant) — This is the conventional ORB invalidation and it comes straight from the script's own drawn levels. With either the opposite-boundary or the midpoint stop, an opposite ORB signal can only occur after the stop has been hit, which removes the conflict with the 'one long + one short per day' rule.
- **What exit or target should be used?** Options: Fixed 2R target measured from the fill, plus flatten at 16:00 NY; 1R or 1.5R target plus flatten at 16:00; No target, flatten at 16:00 only; Target = OR width projected from the breakout level. Recommended: 2R target plus a hard flatten at 16:00 NY; 1R, 1.5R and EOD-only as variant instances — The script stops signalling at 16:00 (lvlSess) but defines no exit. A time flatten keeps the trade inside the window the script uses.
- **What happens to an opposite signal while a position is open, and are the daily counters consumed when no trade is taken?** Options: Ignore it, but consume the day's counter exactly as TradingView would show the marker; Reverse (lab default); Close only. Recommended: Ignore, and consume counters exactly when TradingView would draw a marker — This keeps the signal record identical to TradingView. With the recommended stop the situation almost never arises.
- **Which primary timeframe and OR length?** Options: 5m chart, 15-min OR; 1m chart, 15-min OR; 15m chart, 15-min OR (single bar); Variants with 5-min or 30-min ORs. Recommended: 5m chart with the 15-min OR as the main instance; 1m and 30-min OR as separate variant instances — Your entry timeframe is 5m. The script's tooltip asks for a timeframe no larger than the OR, and the signal bar and EMA values change with the timeframe.
- **Should late-window signals be allowed?** Options: Take every signal through the bar opening 15:55; Skip signals whose next-open fill would be at or after 16:00; No new entries after a cutoff such as 15:00 NY. Recommended: Skip signals whose fill would land at or after 16:00 — The script allows a signal at 16:00 (on the 15:55 bar's close), and the lab's next-open fill would then sit outside the window.
- **Which instruments and days?** Options: NY index instruments only (MNQ1!, NAS100/US100, US30, SPX500/US500); All of your instruments including FX, metals and crypto; Crypto on weekdays only. Recommended: Start with MNQ1!, NAS100/US100, US30 and SPX500/US500; run the others as separate instances. Keep the script's all-days behaviour for parity — A 09:30 NY ORB is built around the US cash-equity open. The script itself does not restrict days or instruments.

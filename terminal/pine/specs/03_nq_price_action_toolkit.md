# Script 3 · NQ Price Action Toolkit (NQ PA)

Source: [`../received/03_nq_price_action_toolkit.pine`](../received/03_nq_price_action_toolkit.pine). Kind: **levels only**. Port complexity: **S** — There is no trading logic to port. Porting it as level providers (FVG/iFVG, session high/low, PDH/PDL, EQH/EQL, fib) is simple bookkeeping. The only parity work is matching session and day boundaries and the FVG inversion rules.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### FVG / iFVG zones (alert-only, no trade logic)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** None defined. bullFVG = low > high[2] and (low - high[2]) >= fvgMinSize (L156). bearFVG = high < low[2] and (low[2] - high) >= fvgMinSize (L157). There is no middle-candle condition. Formation is announced only through alertcondition (L321-322). There is no direction rule, order, or price.
- **Stop:** None.
- **Target / exit:** None. Zones flip to iFVG when a close passes the far side (L176-184). An iFVG is removed when a close passes back through it (L187-192). This is zone bookkeeping, not an exit.
- **Position rules:** None.
- **Timeframes:** Any. Sessions, the 00:00/09:30 opens and NDOG/NWOG need an intraday chart (L106, L200, L226-228).
- **Sessions (New York):** Asia 20:00-00:00, London 02:00-05:00, NY AM 09:30-11:00, Lunch 12:00-13:30, NY PM 13:30-16:00, all with day mask 1234567 (L25-33, L106). Used only for zone tags and session high/low levels. 11:00-12:00 belongs to no session.
- **Defaults:** fvgMinSize=0 points, fvgMax=30, keepDead=false, tagSession=true. Fib pivots 20/20. EQH/EQL pivots 5/5 with tolerance 2.0 points. EMA 9/21.

## Data needs

Intraday chart OHLC with bar open timestamps in America/New_York (DST). Daily bars following the feed's exchange session for the previous-day high/low (L195). Exchange day/week change detection for NDOG/NWOG (L226-229). No volume, no other higher timeframes, nothing external.

## Engine features needed

- None for trading: the script is indicator-only
- If ported as level providers: previous-day high/low from the feed's daily session without lookahead ([1]+lookahead_on semantics)
- NY-time session membership with DST and day mask 1234567
- Exchange day/week change detection (timeframe.change semantics) for NDOG/NWOG

## Building blocks

- FVG (script-3 variant): bull low > high[2], bear high < low[2]. Strict inequality, no middle-candle condition, minimum size in ABSOLUTE points (default 0). Zone = [high[2], low] or [high, low[2]]. Flips to iFVG on a close beyond the far side; an iFVG dies on a close back through it. Plain FVGs are never removed by being filled, only by inversion or by FIFO eviction at 30 (L156-192)
- Session high/low tracker (script-3 variant): reset on the first in-session bar, running max/min, and the levels persist after the session. Explicit day mask 1234567. The NY AM window is 09:30-11:00, unlike script 1's 09:30-12:00 (L25-33, L105-126)
- Session tag precedence for zones: ASIA > LON > AM > LUNCH > PM (L151)
- PDH/PDL via request.security('D', [high[1], low[1], time[1]], lookahead_on) (L195)
- '00:00 open' = the open of the first bar of a new NY calendar date, not necessarily a 00:00 bar (L197-202). This differs from script 1's TDO, which needs an exact 00:00 bar
- 09:30 open = the bar whose open time falls in 09:30-09:31 (L204-210)
- NDOG/NWOG: max/min(open, close[1]) at an exchange day or week change. NWOG takes precedence, so no NDOG is drawn on the first day of the week (L216-229)
- Dealing-range fib from the latest 20/20 pivots at ratios 1.111, 1, 0.83, 0.71, 0.5, 0.29, 0.17, 0, -0.111 (L232-243, L281-318)
- EQH/EQL: two CONSECUTIVE 5/5 pivots within 2.0 absolute points (L246-263)
- EMA 9/21 cloud (L132-136)

## Parity risks

- The alerts (L321-322) are alertconditions on the live, unconfirmed bar. With 'Once per bar' an FVG alert can fire intrabar for a gap that no longer exists at the close. FVG boxes also appear and disappear intrabar on the live bar
- Three different day definitions are mixed: PDH/PDL follow the feed's daily session (L195), the '00:00 open' follows the NY calendar date (L197), and NDOG/NWOG follow timeframe.change on the exchange session (L226-229)
- Session membership is by bar open time via time(timeframe.period, sess + ':1234567', TZ). On 1H futures/CFD bars that start at :00, the 09:30-09:31 window never matches, so the 09:30 open stays na. Session edges at 09:30/11:00/13:30 straddle 1H bars
- Session highs/lows are live running values during the session. Day mask 1234567 includes weekend sessions on 24/7 crypto
- The fib and EQH/EQL levels use pivots confirmed 20 and 5 bars late and are drawn back-dated at time[len] (L240-263)
- The absolute-point thresholds (fvgMinSize, eqTol 2.0) are NQ-specific and meaningless on EURUSD, BTC and similar instruments
- Most levels are drawn only on barstate.islast (L288-318), so the chart shows no history of them. Parity must be checked on computed series, not on drawings

## Behaviour found in the code

- The '00:00 open' is the open of the first bar of each new NY calendar date (L197-202). On instruments without a midnight bar it is mislabelled, and it differs from script 1's TDO (exact 00:00 bar, L463).
- The 09:30 open needs a bar whose open time falls in 09:30-09:31 (L204-210). It is never set on 1H charts with bars that start at :00.
- NDOG/NWOG compare the chart timeframe's close[1] with the open at the exchange day/week change (L216-229). NDOG is skipped on the week's first day because of the else-if. On 24/7 crypto these 'gaps' are just one-bar changes.
- FIFO eviction (L167-168) removes the oldest zone whatever its state. Plain FVGs are never retired by being filled.
- EQH/EQL compare only consecutive pivots, with a 2.0-point absolute tolerance (L253, L259).
- The file carries an MPL-2.0 header (L1). A redistributed Python port of it would be a derivative work under MPL-2.0.

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| confirmed | 3.1 The script defines no entries, stops or exits; its only alerts fire when a fair value gap forms. | L3: indicator(). There are no strategy.* calls, no trade projection and no alert() calls (searched). The only alerts are alertcondition(bullFVG) and alertcondition(bearFVG) (L321-322). Nuances: these alerts are not gated by showFVG and ignore the session tag. There is no alert for an iFVG inversion or invalidation. They can fire on the unconfirmed live bar. |
| confirmed | 3.2 NY AM is defined as 09:30-11:00 here (vs 09:30-12:00 in script 1). | Script 3 L29: amSess default '0930-1100'. Script 1 L71: nyAmSess default '0930-1200'. Both are user inputs. Script 3 also defines Lunch 12:00-13:30 (L31) and NY PM 13:30-16:00 (L33), leaving 11:00-12:00 untagged. Script 3 forces day mask ':1234567' (L106); script 1 sets no day mask (L390). |

## Questions this script raises

- **Should anything in this script become a strategy? It defines no entries, stops or exits.** Options: No strategy; port the FVG/iFVG, session high/low, PDH/PDL and EQH/EQL logic as reusable level providers only; No port at all; User supplies explicit FVG/iFVG entry, stop and exit rules to build a new strategy. Recommended: No strategy; port only as level providers, and only when another strategy needs them. — The porting rules say each tradable setup becomes a strategy and that rules must not be invented. This script has no tradable setup.
- **If these levels are used outside NQ/MNQ/NAS100, how should the point-based thresholds (FVG min size 0, EQ tolerance 2.0 points) scale?** Options: Keep absolute points (NQ only); Convert to instrument ticks; Express as a fraction of ATR. Recommended: Keep the script defaults on NQ/MNQ/NAS100. Convert to ticks only if the levels are used on other instruments. — The script is NQ-specific (title, L61). A 2.0-point tolerance is meaningless on EURUSD or BTC.

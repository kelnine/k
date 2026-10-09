# Script 7 · Order Flow Desk [v6] (07_order_flow_desk.pine)

Source: [`../received/07_order_flow_desk.pine`](../received/07_order_flow_desk.pine). Kind: **levels only**. Port complexity: **L** — Nothing is tradable, but a faithful port of the computed modules needs: lower-TF intrabar arrays with TradingView's candle-direction delta and its fallback; trading-day/week/month anchors matching TradingView for VWAP and CVD; Wilder ATR; pivot-based pool and sweep state machines; absorption shelves; and a redesign of a profile TradingView computes on the last bar only. Parity is unverifiable on 1m charts (needs 15s data), on old bars beyond TradingView's intrabar limit, and on CFD/FX symbols without real volume.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### Liquidity-pool sweep and reject (sweptHi labelled 'Sell-side sweep', sweptLo labelled 'Buy-side sweep')

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Only a boolean condition. sweptHi is true when, for any active high pool level y, high > y and close < y (lines 576-581). sweptLo is the mirror: low < y and close > y (588-593). Pools come from ta.pivothigh/ta.pivotlow(8,8), which confirm 8 bars late (529-530). Every pivot becomes a pool, even one with a count of 1. A new pivot within 0.15 x ATR14 of an existing pool is merged into it (531-539, 553-559), and each side keeps at most 6 pools, oldest dropped first (548-551, 568-571). Output: plotshape (600-601) and alertcondition (815-816). There is no order or price. The script implies a reversal (short after sweptHi, long after sweptLo) but never states it.
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None. The flag is one boolean per bar, however many pools were swept. A pool is consumed on its first sweep or on any close beyond it (582-586, 594-598). Pools persist across days with no session reset. There is no per-day limit and no cooldown.
- **Timeframes:** Any chart timeframe. No HTF requests.
- **Sessions (New York):** None (24h). Not tied to any session.
- **Defaults:** bkPool=true, pivLen=8, poolTol=0.15 x ATR(14), poolKeep=6 per side, poolSweep=true (plot only; the alert fires regardless)

### Absorption shelf (bid/ask)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** absorbed = bkAbs and relVol >= 1.8 and (high-low) <= 0.7 x ATR14 and volume > 0 (line 490). relVol = volume / SMA(volume,20), and the SMA includes the current bar (232-233). Side: delta <= 0 gives a 'bid' shelf at low + 25% of the range (implied bullish); otherwise an 'ask' shelf at high - 25% (bearish) (492, 498). delta comes from the intrabar flow engine (204-230). The alert (814) has no side. The shelf is deleted once close crosses it, provided the shelf is more than 1 bar old (509-519). That deletion is display only and has no alert.
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None. The display keeps at most 6 shelves (504-506).
- **Timeframes:** Any chart timeframe. Delta uses lower-TF intrabars: Auto = 1m for 5m/15m charts, 5m for charts of 1H and above, 15S for 1m charts (199).
- **Sessions (New York):** None (24h)
- **Defaults:** absRv=1.8, absRng=0.7, absKeep=6, volLen=20, ATR(14), ltfChoice=Auto

### Value-area breakout / breakdown

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** alertcondition(not na(vahPx) and ta.crossover(close, vahPx)), plus the VAL crossunder mirror (811-812). vahPx and valPx are computed only when barstate.islast is true (323, 382-383), so the condition can only be true on realtime bars.
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None.
- **Timeframes:** Any chart timeframe
- **Sessions (New York):** Profile window starts at the symbol's TradingView trading-day change (timeframe.change('D'), lines 236, 293), not at the NY open
- **Defaults:** vpMode=Session, vpRows=24, vpVaPct=70

### POC test

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** alertcondition(not na(pocPx) and ta.cross(close, pocPx)) (810). Crosses in both directions count, so there is no direction. Live bars only (pocPx is set only on the last bar, 323/362).
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None.
- **Timeframes:** Any chart timeframe
- **Sessions (New York):** Trading-day anchored (see above)
- **Defaults:** vpMode=Session, vpRows=24

### VWAP cross

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** alertcondition(ta.cross(close, vwap)) (809). The VWAP is the session-anchored hlc3 VWAP (246-272), reset at timeframe.change('D'). Crosses in both directions count, so there is no direction. Unlike the profile alerts, this is evaluated on historical bars.
- **Stop:** None defined (the +-1/2/3 sigma bands exist but are not used as levels).
- **Target / exit:** None defined.
- **Position rules:** None.
- **Timeframes:** Any chart timeframe
- **Sessions (New York):** Anchor = TradingView trading day (default 'Session'); options are Week, Month, Quarter, Year
- **Defaults:** vwAnchor=Session, vwSrc=hlc3, bands 1/2/3 sigma, vwPrev=true

### Delta flip on volume

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** alertcondition(ta.change(math.sign(delta)) != 0 and relVol > 1.5) (813). The 1.5 is hard-coded rather than taken from an input. A move from 0 to +-1 also counts as a flip. There is no direction.
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None.
- **Timeframes:** Any chart timeframe; intrabar delta (Auto LTF)
- **Sessions (New York):** None
- **Defaults:** volLen=20, ltfChoice=Auto

### Gamma flip cross / gamma wall touch

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** flipCross = gxFlip > 0 and ta.cross(close, gxFlip) (686). nearWall = |close - wall| / close x 100 <= 0.15 for the call or put wall (684-685). Alerts are on 817-818. Every level is a static number the user types in, and all default to 0 (off).
- **Stop:** None defined.
- **Target / exit:** None defined.
- **Position rules:** None.
- **Timeframes:** Any chart timeframe
- **Sessions (New York):** None
- **Defaults:** gxFlip=0, gxCall=0, gxPut=0 (all off), gxMagnet=0.15%, gxZone=0.10%

## Data needs

Chart-timeframe OHLCV, any intraday timeframe. Lower-timeframe intrabar OHLCV+time arrays via request.security_lower_tf (204-205): Auto picks 1m for 5m and 15m charts, 5m for 1H and above, 15S for 1m charts and 5S below that. Our feed has no seconds bars, so 1m charts must use the close-position fallback. Bar volume and intrabar volume. Real exchange volume exists only on MNQ1! and the crypto symbols; the FX/metal/index CFDs carry tick volume or none. Trading-day boundaries matching TradingView's timeframe.change('D') (VWAP, CVD, profile), plus W/M/3M/12M boundaries for the optional VWAP anchors and the CVD weekly reset. ATR(14) and SMA(20) of volume. External, manually typed gamma levels. No HTF request.security and no daily bars as data.

## Engine features needed

- No order or position features: the script has no tradable setup
- Lower-TF intrabar arrays aligned to each chart bar (1m inside 5m/15m, 5m inside 1H); seconds bars are not available
- Bar volume plus intrabar volume
- Trading-day / week / month / quarter / year boundary detection per symbol, matching TradingView's timeframe.change (catalog trading-day rule)
- Wilder ATR(14) and SMA with Pine warm-up semantics
- Pivot detection with an N-bar confirmation delay
- Stateful registries that persist across bars: liquidity pools and absorption shelves
- If the POC/VA alerts are ported: a per-bar-close rolling session volume profile. This is a new design, because TradingView computes the profile on the last bar only
- If gamma alerts are ever used: a dated table of external levels

## Building blocks

- Intrabar delta (script-7 variant). Each LTF bar's volume goes to buy if close > open, to sell if close < open, and is split 50/50 on a doji. Fallback when there are no intrabars: buy = volume x (close-low)/range, with range floored at mintick (212-227)
- Relative volume = volume / SMA(volume,20). The SMA includes the current bar, and nz() makes relVol 0 during warm-up (232-233)
- ATR(14) via ta.atr (Wilder RMA), nz() fallback to mintick (234)
- Anchored VWAP of hlc3 with volume-weighted population-variance sigma bands. Anchor = timeframe.change of D/W/M/3M/12M. Weight = 1 when bar volume is 0. Carries the previous anchor's closing VWAP (246-287)
- CVD reset at the trading-day change (default) or the week change (236-241)
- Volume profile (script-7 variant). Window = bars since the trading-day start, including the current bar, minimum 2 and maximum 2000 bars. 24 rows across the window's high-low range. Each bar's volume is split EQUALLY across the rows it touches, not by overlap. Buy share = close position. POC = first row with the maximum volume. The 70% value area grows one row at a time toward the heavier neighbour, ties going up. POC = row centre, VAH = top of the top row, VAL = bottom of the bottom row, none rounded to tick. Computed on the last bar only (308-383)
- ta.pivothigh/ta.pivotlow(8,8): confirmed 8 bars late, tie handling exactly as Pine's
- Liquidity pools (script-7 variant). Every pivot is a pool. A new pivot merges into the first pool within 0.15 x ATR measured at the confirmation bar; the pool keeps its original level and its count goes up. Max 6 per side, oldest dropped first. A pool is removed when swept or when a bar closes beyond it (521-598)
- Sweep (script-7 variant): the wick goes through the pool level and the close comes back to the other side. The pool is consumed
- Absorption: relVol >= 1.8 and range <= 0.7 x ATR. Side from the delta sign. Shelf at 25% into the bar. Invalidated when close crosses it
- Display only: HVN/LVN (>1.6x / <0.35x average row), heat map, tape, bubbles, dashboard

## Parity risks

- The POC/VAH/VAL profile exists only from the last historical bar onward (var na at 301-303, assigned inside barstate.islast at 323). On TradingView the three profile alerts are never true historically, so a Python historical profile cannot be checked against TradingView
- Live repaint: on every realtime tick the profile is rebuilt over a window that includes the forming bar. When the session high or low extends, rowH changes and POC/VAH/VAL jump, so a 'cross' can come from the level moving rather than from price. The lab evaluates only on closed bars
- Pine v6 evaluates 'and' lazily, so the ta.cross/crossover/crossunder calls in 810-812 run for the first time on the last bar, with no history. They are false on that bar too
- Intrabar delta source. TradingView uses request.security_lower_tf; Auto = 15S on 1m charts, which needs a seconds-data plan, otherwise it falls back. Our feed has no seconds bars. TradingView's intrabar history is limited (about 100k intrabars), so older chart bars silently use the close-position estimate. On the live bar the arrays are partial. Intrabar volumes differ between data vendors
- Volume quality: CFDs/FX on TradingView (XAUUSD, EURUSD, NAS100 and others) carry tick volume or none, and our feed's volume is synthetic. With zero volume the VWAP falls back to equal weights (267). Relative volume, absorption, bubbles and delta all change
- Trading-day anchors follow TradingView's symbol session (timeframe.change('D'/'W'/...)): CME 18:00 ET, FX/metals 17:00 ET, crypto 00:00 UTC. The catalog's trading-day rule must match the specific TradingView symbol the user charts
- Warm-up: SMA(20) through nz() gives relVol 0 for the first 19 bars, and ATR falls back to mintick. Pine's RMA seed for ta.atr must be replicated
- Pivot confirmation delay and tie semantics must match Pine. Pool lines are back-dated to bar_index - pivLen (546, 566)
- Processing order within a bar matters: new pivots are merged or added (533-571) before the sweep and removal pass (576-598)
- Gamma levels are a single static input applied to every historical bar (regime bgcolor 688, nearWall/flipCross 684-686). Historical evaluation therefore uses today's levels, which is look-ahead by construction
- 'Visible range' profile mode depends on the chart's scroll position (chart.left_visible_bar_time, 317) and cannot be reproduced
- alertcondition alerts can trigger intrabar on TradingView unless set to 'Once per bar close'; the lab sees closed bars only

## Behaviour found in the code

- The 'liquidity pools' are not equal highs/lows only. Every confirmed 8/8 pivot becomes a pool with count 1 (544-545, 564-565); 'equal' (within 0.15 x ATR) only merges pivots. The sweep alerts (815-816) therefore fire on any swing-high/low sweep, despite the alert text saying 'equal highs/lows'
- The sweep naming is inverted relative to ICT usage. A sweep of a high is labelled 'Sell-side sweep' and a sweep of a low 'Buy-side sweep' (600-601, 815-816). Do not map it onto script 1, 2, 4 or 5 sweep definitions without checking
- A pool is consumed by its first sweep or by any close beyond it (582, 594). A close exactly at the level leaves the pool alive. A swing younger than 8 bars cannot be swept because it is not a pool yet
- Pool merges keep the original level and use the ATR at the confirmation bar. A new pivot above an existing high pool can never merge, because the pool would already have been removed when price traded through it
- Likely bug: 'Off' intrabar resolution sets ltfRes to the chart timeframe (200). request.security_lower_tf at the chart's own timeframe probably returns a one-element array rather than an invalid result. If so, delta becomes 100% of volume in the candle's direction, not the close-position estimate the tooltip promises (53). Verify on TradingView
- On 1m charts, Auto requests 15S data (199). Without a seconds-data plan, TradingView silently uses the close-position estimate; with one, results depend on the plan. Older bars beyond the intrabar limit also use the estimate, so the delta method changes partway through the chart
- The profile's buy/sell split (vpBuy/vpSell and rowsBuy, 349-357) always uses the close-position estimate, even when intrabar delta is available. The dashboard's 'Profile B/S' therefore disagrees with the flow engine
- The delta-flip alert hard-codes relVol > 1.5 instead of using an input, and counts 0 to +-1 as a flip (813)
- Absorption side is set by delta <= 0, so zero delta counts as a 'bid' (bullish) shelf (492). The absorption alert carries no side
- relVol includes the current bar in its own 20-bar average (232), which damps spikes
- VWAP gives zero-volume bars weight 1.0 (267). On symbols with no volume it becomes an equal-weight average, and when mixed with real volume such bars are effectively ignored
- The profile window is capped at 2000 bars and floored at 2 bars (311, 321). Before the first day change sessStart is 0, so the window runs from bar 0
- The 'prints tape' shows lower-timeframe bars at least 2.5x the average sub-bar volume, not actual trades (725-735)
- Bubble labels are never deleted; TradingView keeps only the newest 500 labels. Display only

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| confirmed | 7.1 No entries or exits; alerts only. | Line 33 declares indicator() and there are no strategy.* calls anywhere (grep). Outputs are VWAP plots (277-287), sweep plotshapes (600-601), drawings and tables, and 10 alertcondition() calls (809-818). None defines an entry price, stop or target. VWAP cross, POC test, delta flip, absorption and gamma wall touch do not even define a direction. |
| confirmed | 7.2 The session volume profile (POC/VAH/VAL) is only computed on the last bar, so the POC-test and value-area alerts cannot fire on historical bars, only live. | pocPx/vahPx/valPx are declared 'var float = na' (301-303) and assigned only inside 'if barstate.islast and (vpShow or dshShow)' (323, 362, 382-383). On every historical bar except the last they are na, so 'not na(...) and ...' (810-812) is false. Because Pine v6 'and' is lazy, the ta.cross/crossover/crossunder calls first run on the last bar with no history, so they are false there too. On realtime bars barstate.islast is true on every tick, so the profile is rebuilt and the alerts can fire. Nuances: (a) 'Session' means since timeframe.change('D') (236, 292-294), i.e. the symbol's TradingView trading day, not NY RTH. (b) The same last-bar-only limitation applies to the 'Fixed lookback' and 'Visible range' modes. (c) Live, the window includes the forming bar and is rebuilt each tick, so a cross can be caused by the level jumping. (d) With both vpShow and dshShow off, the levels are never computed. |
| confirmed | 7.3 Gamma flip/call wall/put wall are fixed numbers typed into the settings; nothing is computed from options data. | Lines 114-124: gxFlip/gxCall/gxPut are input.float with default 0 (= off), gxExtra is a typed string, and gxStep is a typed spacing. The header (24-26) says they are pasted in from an options provider. The only computation is the strike grid around the last close (641), the nearest-level selection (668-680) and the regime/magnet/cross tests (682-686). None uses options data. Note: one static value is applied to every historical bar (bgcolor 688, alerts 817-818), and everything gamma-related is off by default. |

## Questions this script raises

- **Script 7 defines no entry/stop/target for anything. Should any strategy be built from it?** Options: Port only as an indicator/level library (VWAP bands, pools/sweeps, absorption, delta) with no strategy; Build a pool-sweep reversal strategy once you supply stop and target rules; Build a value-area breakout strategy once you supply stop and target rules. Recommended: Port as a level library only; create no strategy until you give stop and target rules — Your rule: only tradable setups become strategies. Every output here is an alert with no stop or target, and several (VWAP cross, POC test, delta flip, absorption, wall touch) have no direction either.
- **TradingView computes the session volume profile on the last bar only. What should backtests use?** Options: Skip POC/VA logic in backtests; Rolling profile rebuilt at each closed bar over the trading day so far (what a 'once per bar close' live alert would see); Previous trading day's completed profile (non-repainting). Recommended: Rolling profile at each bar close, marked as 'not verifiable against TradingView history' — Nothing on TradingView can be compared historically. The rolling version reproduces what the live alerts would evaluate at each bar close.
- **Which delta source should be used on our feed?** Options: 1m intrabars for 5m/15m, 5m for 1H, close-position estimate on 1m charts; Close-position estimate everywhere. Recommended: 1m intrabars for 5m/15m, 5m for 1H, close-position estimate on 1m (no seconds data) — This matches TradingView's Auto choice wherever our data allows it.
- **How should volume-based logic be handled on instruments without exchange volume (XAUUSD, XAGUSD, EURUSD, GBPUSD, NAS100/US100, US30, SPX500 CFDs)?** Options: Enable volume logic only on MNQ1! and the crypto symbols; Use whatever tick volume the feed provides. Recommended: Enable only on MNQ1! and crypto — VWAP, relative volume, absorption and delta are meaningless or vendor-specific without real volume.
- **What should be done with the gamma levels?** Options: Leave them disabled (script default 0); Supply a dated per-day table of flip/call/put levels. Recommended: Disabled — A single static value applied to all history is look-ahead, and the script computes nothing from options data.

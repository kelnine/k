# AIO Trading Suite [K] — Performance Edition v1.0 — Audit & Validation Report

**Status: not yet compiled or run on TradingView.** The script was written against the
Pine v6 reference. No compiler, Pine Profiler or TradingView account was available
while writing it. Nothing below is a measured result. Every cost figure is an estimate
from reading the code. Section 7 is the test procedure that turns these estimates into
real numbers.

File: `pine/AIO_Trading_Suite_K_v1.0.pine` (one indicator, overlay).

---

## 1. Stage A — audit of the three original scripts

### Script 1 — MTF Trend Dashboard + FVG Zones

| Item | Finding |
|---|---|
| Heaviest cost | **8 `request.security()` calls, all always on.** Each one runs the full trend function (2 pivots + 2 EMAs) over its own copy of history. The **1m and 3m rows on a 5m/15m chart are lower-timeframe requests**, so they load and process 5–15× more bars than the chart itself. This is likely the main cost in this script. |
| Repainting | The calls use the default `lookahead_off` without `[1]`. On realtime bars the 15m/1H/4H/D/W rows show the **still-forming** higher-TF candle, so they can flip and later disagree with history. The "all timeframes agree" alert inherits this. |
| FVG | Every bar loops over all active zones and calls `box.set_right`/`line.set_x2` on each. That costs 10 zones × 2 calls × every historical bar, and only the final position is ever drawn. |
| Drawing risk | "Keep mitigated zones" never deletes boxes. Alone that is harmless. Merged with other modules, TradingView's 500-box garbage collector would delete the *oldest* boxes, which could include live ORB or zone boxes. |
| Naming | It uses `method` as a variable name, which is a v6 keyword. It also has `emaFast`/`emaSlow`/`t1` names that clash with Script 2. |

### Script 2 — FRVP + ORB + 9/20 EMA

| Item | Finding |
|---|---|
| FRVP cost | The profile is **not** rebuilt over full history. It is rebuilt only on `barstate.islast`. On the realtime bar, though, that means **every tick**: about bars × rows-covered of work, plus deleting and recreating up to about 2·rows+1 boxes, 3 lines and 3 labels. Latest NY session on 1m (390 bars × 24 rows) is cheap. "Pick on chart" or "Last N = 5000" with 100 rows can reach hundreds of thousands of loop steps **per tick**. |
| FRVP accumulation | It pushes 4 values per bar into arrays (cheap). "Previous session" allocates new arrays each session (cheap). |
| ORB | Cheap. The signal is gated on `barstate.isconfirmed` and needs a complete range, so it does not repaint. Range completion happens on the first bar after the window. There is one ORB only. |
| EMAs | Cheap. They are duplicated across scripts 2 and 3 (EMA 9) and script 3's EMA 200 overlaps the ribbon. EMAs are trivially cheap, so sharing them saves almost nothing. |

### Script 3 — Auto Trendline Detector Pro

| Item | Finding |
|---|---|
| Heaviest cost (whole suite) | On every confirmed swing, up to `pairDepth` (6) candidates each run `f_validate` over the full span (up to `maxAnalyze` = 400 bars). Each step reads `atr`, `high/low`, `close` **with a variable history offset**. Rough average: ~2 × 6 × 400 / ~15 bars per pivot ≈ **300 loop steps per bar**, over all history. |
| Wasted work | **The rendering block ran on every historical bar.** It set position, colour, width and style on every line, and for each broken line it re-scanned all lines (O(n²)). Only the last bar's result is visible. |
| Avoidable work | `f_alreadyBroken` (≤ L bars) was checked *after* the 400-bar validation, even though either check alone can reject the candidate. Validation also kept scanning after the candidate had already exceeded the allowed violations. |
| Memory | `max_bars_back = 1100` sizes the history buffer of **every series** in the script. Only 4 series need it. |
| Repainting | Clean. Pivots are used L bars late, all state changes are gated on closed bars, and there are no security calls. The swing markers use `offset = -L` (drawn at the true bar after confirmation), which is a documented display convention. |
| Bug (display only) | `setupIdx` held an array index. When lines were removed or pruned, the indices shifted and clean mode could highlight the wrong line. |

---

## 2. How the merge is built

* One indicator, one `ta.atr(14)` shared by FVG, trendlines and ORB retests. There is one compact dashboard instead of two tables.
* All name clashes are resolved (`mt1..mt8`, `emaF/emaS`, `tlHi/tlLo/tlCl`, `fvgExtend`, `tlExtend`, `vpTz`, …).
* `calc_bars_count = 3000` limits the initial calculation to the last 3000 bars. It shows up as **Settings → Calculated bars**, so you can raise or lower it. This is the biggest single lever against RE10110. It does not change recent signals, because every module needs far fewer than 3000 bars of warm-up (EMA 200 converges within about 600–800 bars).
* Every major module has its own ON/OFF switch. Disabled modules skip their per-bar work. MTF rows that are disabled, or skipped in Lite, sit inside `if` blocks (v6 dynamic requests), so they should not be fetched. **Check this in the Profiler.**

---

## 3. List of altered calculations (nothing else was changed)

| # | Module | Change | Effect on signals |
|---|---|---|---|
| 1 | MTF | New input **Higher-TF values**, default **Confirmed**. Higher-TF rows use `f()[1]` + `lookahead_on`, so they show the last *closed* candle. Rows at or below the chart TF are unchanged. **Live (original)** restores the original behaviour exactly. | The dashboard now matches history. HTF rows update one candle later than the live original. |
| 2 | MTF | `method` input renamed internally (`mtfMethod`). Same options. | None. |
| 3 | MTF (Lite only) | Rows whose timeframe is **below** the chart TF are hidden and not requested (e.g. 1m and 3m on a 5m chart). | Those rows are missing in Lite. The agreement alert ignores them, just as it did for rows the user switched off. |
| 4 | FVG | Live zones are re-extended on the last bar only. | Display identical. |
| 5 | FVG | "Keep mitigated" is capped (default 10) so the shared 500-box limit can't delete other modules' boxes. Lite caps active zones at 5 and disables kept zones. | Fewer old boxes. Detection unchanged. |
| 6 | FRVP | Default **off**. New **Refresh = On bar close** (forced in Lite): rebuilt on load and once per closed bar instead of every tick. | POC/VAH/VAL math is **identical**. The live bar is added when it closes. "Every tick (original)" is still available in Standard. |
| 7 | FRVP | **Max bars in profile** (default 2000). If a range is longer, only the latest N bars are profiled and the POC label says `(latest N bars)`. | Only affects very long ranges, and it is shown on the chart when it happens. |
| 8 | ORB | The single ORB is replaced by **three** (London 03:00–03:15, NY 09:30–09:45, Globex 18:00–18:15, America/New_York). The NY defaults equal the original (`0930-0945`, active `0930-1600`, EMA filter on, first close outside, one long + one short per range). | NY signals should match the original's. |
| 9 | ORB | New: retest confirmation, "require complete range data" (default on), unsupported above 15m. | Additive. A range with a missing bar is skipped instead of drawn partially. |
| 10 | Trendlines | `f_alreadyBroken` is checked before `f_validate`. Validation exits early once violations exceed the limit. | **Identical** accepted lines and scores. |
| 11 | Trendlines | Rendering runs on the last bar only. `setupIdx` is replaced by a stable line id (bug fix). | Display identical, except that clean mode now highlights the correct setup line. |
| 12 | Trendlines | Global `max_bars_back = 1100` is replaced by per-series `max_bars_back(…, 1100)` on the 4 series that need it. | None. |
| 13 | Trendlines | The EMA 9/21/50/200 plots default **off**, because section 5 and the ribbon already draw EMAs. They are still calculated for the trend and filters. Global Clean Mode / Lite force trendline clean display, and Lite keeps 10 labels instead of 30. | Display only. |
| 14 | Dashboard | One table. Default text **Small** (was Normal). Trendline rows condensed from 5 to 4 (Resistance/Support merged into "TL lines"). | Display only. |

---

## 4. Basic Lite vs Standard

| Feature | Basic Lite (default) | Standard |
|---|---|---|
| MTF dashboard | On. Only rows ≥ chart TF are requested | All enabled rows |
| EMA 9/20 | On | On |
| EMA 200 ribbon | On | On |
| Three 15m ORBs | On, latest range only | On, history per input |
| 4H supply/demand | On, nearest 2 per side | Same (configurable) |
| FVG | ≤ 5 active, no kept history | Per input |
| Trendlines | Full detection (unchanged), clean display, 10 labels | Full display options |
| Volume profile | Off by default. If on, refreshed on bar close | Optional every-tick refresh |

Lite never computes a signal differently from Standard. It only skips modules, rows or
drawings, so any signal that *is* shown is identical in both modes.

**Trendline detection settings are not changed in Lite**, because changing them would
change which lines exist and when signals fire. If the Profiler shows trendlines are
still too heavy on your account, the honest knobs are **Maximum bars to analyze**
(400 → 250) and **Anchor pairing depth** (6 → 4). They cut the work roughly in
proportion, and you'll see slightly different lines.

---

## 5. New modules — exact rules

### Three 15-minute ORBs
* A window is valid only if chart bars tile it exactly: **1m, 3m, 5m, 15m** for 15-minute ranges. On 30m/1H and above the dashboard shows `n/a`, and no levels or signals are produced.
* The range is complete on the first bar after the window. Breakout = first **closed** candle beyond high/low while the "levels active" session runs (+ optional EMA filter). Retest = a later closed candle wicks back to the level (± tolerance × ATR) and closes beyond it again. A close back inside first cancels the retest.
* London has a second mode, **08:00 Europe/London**, because UK and US clocks change on different dates.
* On 24/7 crypto, the 18:00 window is only a scheduled time window. On stocks, 03:00 and 18:00 have no bars, so no range is drawn.

### 4H supply & demand
* The detection function runs **inside the 4H context**, and its result is read with `[1]` + `lookahead_on`, so the chart only sees a zone once its 4H displacement candle has closed.
* Demand: bullish 4H candle with body ≥ 1.5 × ATR(14), closing above the prior 10-candle high (toggle). The zone is the 1–3 preceding small-body base candles (body ≤ 0.6 × ATR). If there is no base, the single prior candle is used. Proximal edge = bodies (or wicks), distal edge = wick extreme. Zones taller than 2 × ATR are rejected. Supply mirrors this.
* States: **fresh**, then **tested** (first closed chart candle touching the zone), then **mitigated** (price reached 50%), then **invalidated** (completed 4H close beyond the distal edge by default, or a closed chart-candle wick beyond it).
* Overlapping new zones on the same side are skipped. Up to 8 zones are tracked per side. The nearest 2 are drawn through a reused box pool (at most 2 + 2 boxes).
* Disabled above the 4H chart timeframe.

### EMA 200 high/close ribbon (approximation)
The PB-EMA source was not provided. From the screenshots: a band between two 200-period
EMAs, green/red fill, darker edges. My reading is **EMA(high) and EMA(close)**. What the
screenshots cannot show:
* The exact sources. They could be high/close, or something like high/low with close used only for colour.
* The colour rule. The 1H screenshot turns green only while price is above the band during a downward-sloping EMA, which rules out a pure slope rule. The default is therefore **"Close beyond band (hold inside)"**: green after a close above the whole band, red after a close below it, and the colour is held while price closes inside. "Close vs EMA(close)" and "slope" are selectable.

If you paste the PB-EMA source later, this section will be replaced with its exact formula.

---

## 6. Known limitations

1. **Not compiled or profiled yet.** Expect a few compiler messages on the first paste. Send them as-is.
2. Dynamic requests (`request.security` inside `if`) are assumed to skip disabled MTF rows. If the Profiler still shows time for disabled rows, the fallback is to remove those rows' code paths.
3. The 4H zone request always runs, even when the module is off (a tuple request can't be placed in a conditional block). It is one 4H context, which should be cheap.
4. `calc_bars_count = 3000`: on 1m that is about 2 days of history for drawings and markers. Raise it in Settings if you need more.
5. ORBs are unsupported above 15m by design. Lower-timeframe aggregation was judged not worth its cost for a 5m/15m trader.
6. Supply/demand zones are price-action estimates, not order-flow data.

---

## 7. Stage D — test procedure (please run and report back)

Run it in this order. Each step turns modules on or off **in the inputs**. No code edits are needed.

1. **Compile.** Paste the script into a new Pine Editor tab and click *Add to chart*. Send me any error **exactly** (line number + message).
2. **Baseline (single modules)** on HYPE 5m. Turn everything off except one module at a time: MTF → FVG → EMA/ribbon → ORBs → 4H zones → trendlines → FRVP. Note any RE10110.
3. **Profiler.** In the Pine Editor, open the "More" (…) menu and choose *Profiler mode*. Screenshot or copy the **top 10 lines by time**, with all Lite defaults on.
4. **Lite defaults** on BTC, SOL, HYPE and NQ (or MNQ), on 1m, 5m, 15m and 1H. Note RE10110 or "loading" stalls.
5. **Standard** with FRVP on, same matrix (5m and 15m are enough).
6. **Reload check.** Note the last 3 ORB markers, trendline labels and 4H zones. Reload the chart (or switch symbol and back) and confirm they are identical. Repeat after one new 4H candle closes.
7. **ORB timing.** On 5m NY: the range box must cover 09:30–09:40 bars only, and the first possible signal is the 09:45 bar's close. Switch to 1H and the dashboard must show `ORB 15m … n/a`.
8. **Original parity.** Load the original Auto Trendline Detector Pro next to the suite (Clean Mode off, Standard). Breakout/retest labels should appear on the same bars.

If a step fails, the error text plus the Profiler's top lines is enough for me to fix the
specific component and send a corrected build.

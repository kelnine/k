# Multi-Session ORB Pro — TradingView Pine Script v6

Opening-range breakout (ORB) toolkit for **MNQ / NQ futures** and **crypto perpetuals**
(BTC, SOL, NEAR, ZEC, …), built for the 5-minute chart.

| File | What it is |
|---|---|
| [`MultiSessionORBPro.pine`](MultiSessionORBPro.pine) | The indicator: four session ranges, signals, trade levels, dashboard, alerts |
| [`MultiSessionORBPro_Strategy.pine`](MultiSessionORBPro_Strategy.pine) | Separate `strategy()` for backtesting the exact same signals |
| [`tools/check_shared.py`](tools/check_shared.py) | Proves the two scripts share a byte-identical signal engine |
| [`tools/lint_pine.py`](tools/lint_pine.py) | Offline syntax + name / field / parameter / na-comparison checks |
| [`tools/engine_reference.py`](tools/engine_reference.py) | Python model of the engine + session-time table generator |
| [`tools/test_engine_reference.py`](tools/test_engine_reference.py) | 25 unit tests for sessions, DST, missing bars, signals, exits |

> **Compilation status.** The indicator compiles and runs in TradingView: it was
> tested on a SOLUSDC.P 5 m chart (Hyperliquid) on 2026-11-24. That first run exposed a
> bug, now fixed: no session window ever started, because Pine evaluates
> `x != na` as false. The second run hit runtime error RE10110 (execution time limit).
> The per-bar work has since been cut sharply: timezone maths now runs about once a day
> per session instead of on every bar, the extra same-timeframe data request is gone,
> and the dashboard caches next-window times. The strategy has not been compiled in
> TradingView yet. Offline,
> both files parse with an open-source Pine grammar, pass the static checker (names,
> built-ins, keyword arguments, type fields, and `==` / `!=` against values that can be
> `na`), share identical engine blocks, and the engine logic passes 25 reference tests.
> If the Pine Editor reports an error, send me the line number and message.

> **No performance claims.** Nothing here says any preset is profitable. Use the
> strategy script to measure it on your own data, costs and settings.

---

## 1. What it does

### Sessions (each in its own IANA timezone)

| Session | Local window | Timezone | Default days (local date) | Futures | Crypto |
|---|---|---|---|---|---|
| New York (NYSE cash open) | 09:30–09:45 | `America/New_York` | Mon–Fri | on | on (reference) |
| London (LSE cash open) | 08:00–08:15 | `Europe/London` | Mon–Fri | on | on (reference) |
| CME Globex (evening reopen) | 18:00–18:15 | `America/New_York` | Sun–Thu | on | on (reference) |
| Tokyo (TSE cash open) | 09:00–09:15 | `Asia/Tokyo` | Mon–Fri | off | on (reference) |

Window starts are built with `timestamp(<IANA zone>, y, m, d, hh, mm)` on the
session's **local** date, so the timezone database handles every daylight-saving
change. You do not adjust anything when clocks change. In New York time:

* London opens at **03:00 ET** most of the year, and at **04:00 ET** during the short gaps
  when only the US has changed its clocks (2026: Mar 9–27 and Oct 26–30; 2027: Mar 15–26 and Nov 1–5).
* Tokyo 09:00 JST is **19:00 ET (US winter) / 20:00 ET (US summer)** on the *previous* NY date.
* CME 18:00 ET is 22:00 UTC in summer and 23:00 UTC in winter. The Sunday window is the weekly reopen.

On crypto charts every window is a **reference window**. Crypto trades all the time, so
there is no real "open" at these times. By default each window keeps its own weekday
calendar. Turn on *Crypto: form reference windows 7 days a week* to include weekends.

Each session has its own: enable switch for futures and for crypto, timezone, start
time, duration (5 / 15 / 30 / 60 min), weekday checkboxes, holiday list and colours.

**Holidays.** Pre-filled full-day closures for 2025–2027 (taken from exchange
calendars) for NYSE, LSE and JPX. Without them a fake "cash open" range would form,
because MNQ/NQ trade at 09:30 ET on NYSE holidays and at 08:00 London on UK bank
holidays. The CME list is intentionally empty. On futures charts an evening with no
Globex reopen has no bars, so no range forms anyway, and a wrong date could hide a
real range. **Extend the lists every year.** The dashboard warns when the current
year has no dates in a list.

### Opening range

* ORH = highest **wick high**, ORL = lowest **wick low** of the bars inside the window.
  Standard candles, bars or line charts only. Heikin Ashi and other synthetic chart
  types distort wick highs and lows, so ranges are disabled there, with a warning.
* A shaded box grows while the range forms. ORH / ORL are **frozen only when the last
  window candle closes**. If that candle is missing, they freeze on the first bar after
  the window, before that bar is evaluated.
* After freezing: ORH / ORL lines (plus an optional 50 % midpoint) extend right.
  Labels read `NY ORH 21050.25 · 2h`: session, level, price and the age of the level.
* Optional **1-hour range** drawn alongside (display only; signals use the primary range).
* **Stale-level protection** (the far-away-old-levels problem):
  * Every range is tied to a dated window, and the box is labelled `NY 11-24`.
  * Levels expire after *Level lifetime* (default 12 h) or when the same session's next
    window starts, whichever is first. Expired levels stop extending, turn dotted and
    faded, and their labels disappear.
  * When a window doesn't happen (weekend, holiday, no bars), nothing is carried forward.
  * The dashboard shows `Waiting · Mon 09:30` and `—` for the range once levels expire.
* **Timeframe guard.** A range is only built when whole chart bars tile it exactly
  (15-min range → 1 / 3 / 5 / 15 m; 1-hour range → also 20 / 30 / 60 m). Unsupported
  timeframes are **disabled with a warning**, never approximated. A runtime check also
  flags bars that straddle the window edges.
* **Clean mode** shows only the latest session's drawings. Keep 1–10 historical sessions
  per market otherwise. Drawings are pooled and trimmed so TradingView's 500-object
  limits are never reached.

### Signals (confirmed candle closes only)

| Entry mode | Long signal (short is mirrored) |
|---|---|
| Breakout close | Candle **closes** above ORH + min distance |
| Breakout + retest | A breakout first; then, within *Max bars*, a later candle trades back to ORH ± tolerance and closes back above ORH (optionally a green candle). A close back inside cancels the setup. |
| Breakout + momentum | Breakout close **and** a strong candle: body ≥ X % of its range, range ≥ Y × ATR |

* Never while the range is forming. Only bars that *start* after the window are evaluated.
* Options: direction (both / long / short), first breakout per session only, max signals
  per session, max bars to wait for the retest, minimum breakout distance, signal window
  (minutes after the range), one signal per bar across sessions (priority NY → LDN → CME → TKY),
  no new signal while that session's tracked trade is open.
* A direction re-arms only after a close back inside the range, so a trend above ORH
  does not produce a signal on every bar.
* **False-breakout warning**: price closes back inside the range within N bars of a breakout.
* Distances (min breakout, retest tolerance, stop buffer, break-even offset) are in
  **ticks** (`syminfo.mintick`) or **ATR multiples**, set separately for futures and crypto.

### Optional filters (all off by default)

EMA 9/21 alignment · EMA 50/200 trend · volume > k × SMA · ATR ≥ k × its SMA ·
range size between min % and max % of daily ATR(14) · RSI thresholds ·
higher-timeframe close vs EMA. Higher-timeframe values use
`request.security(…, expr[1], lookahead = barmerge.lookahead_on)`, which means the
**previous confirmed candle** only, so they never repaint.

### Entries, stops, targets

Entry = signal candle close. Stop = opposite OR boundary, OR midpoint, or ATR from
entry (plus a buffer). TP1 / TP2 = R multiples. Optional break-even after TP1. All
prices are rounded with `math.round_to_mintick`. Futures and crypto blocks are
independent. Trades are tracked bar by bar. If one candle touches both the stop and a
target, the **stop is assumed first** (conservative). Tracked trades close at level
expiry or after an optional time limit.

### Dashboard

Session · Status (`Waiting`, `Forming`, `Range`, `Breakout`, `Breakout · retest?`,
`In trade`, `False breakout`, `Done · TP2`, …) · Direction (Bull / Bear) · Range size.
Also the timeframe, profile, current session, the full range read-out (points,
ticks or %, % of daily ATR), mode and filters, multi-timeframe bias and warnings.
It can be moved to 8 positions or turned off. **Validation mode** adds each window's
start in New York time and UTC.

---

## 2. Installation

### Desktop (browser or desktop app)

1. Open a chart and click **Pine Editor** at the bottom.
2. Open the editor's script menu → **Create new → Indicator**. Select all the template text and delete it.
3. Paste the full contents of `MultiSessionORBPro.pine`, click **Save** (name it), then **Add to chart**.
4. If the compiler shows an error, note the line number and message (see the compile status above).
5. Repeat with `MultiSessionORBPro_Strategy.pine`, choosing **Create new → Strategy**. Open
   **Strategy Tester** for the results.
6. **Futures charts must show extended (ETH) hours.** Otherwise London, CME and Tokyo have
   no bars. The dashboard warns about this.

### Mobile (iOS / Android)

The Pine Editor is mainly a desktop / web tool, and menu names differ between app versions.

1. Save both scripts once from a computer, or open tradingview.com in the phone's
   browser with **Desktop site** turned on and follow the desktop steps.
2. In the app, open a chart → **Indicators** (ƒx) → **My scripts / Personal** → tap
   *Multi-Session ORB Pro*.
3. Settings: tap the indicator name on the chart → gear icon. Use *Clean mode*,
   *Text size: Tiny* and a *Top left* / *Bottom left* dashboard on small screens.
4. Alerts made in the app work the same way as on desktop (next section). Alerts run on
   TradingView's servers, so they fire even when the app is closed.

---

## 3. Recommended starting inputs

These are **starting points to test**, not tuned or proven settings.

### MNQ / NQ (5-minute chart, ETH session, continuous contract e.g. `MNQ1!`)

| Setting | Value |
|---|---|
| Market profile | Auto-detect (dashboard should say *Futures*) |
| Sessions | NY on, London on, CME on, Tokyo off; 15-min ranges |
| Entry mode | Breakout close as the baseline; then compare Breakout + retest |
| Max signals / session | 2 · First breakout only: off (test both) |
| Signal window | 180 min · Level lifetime 12 h |
| Futures block | Ticks · min breakout 2 · retest tolerance 8 (2 pts) · stop *Opposite OR boundary* + 2 ticks · TP1 1 R · TP2 2 R · break-even after TP1 + 1 tick |
| Filters | None first; then test one at a time (HTF 60-min EMA 50, range size 5–60 % of daily ATR) |
| Strategy → Properties | Commission: *per contract*, your broker's all-in cost per side (usually under $1 for MNQ, a few dollars for NQ). Slippage 1–2 ticks. Initial capital 25 000 (raise it for NQ). |
| Strategy → Backtest | Fixed 1 contract (TP1 then only moves the stop to break-even) or 2 contracts (half off at TP1) |

### Crypto perpetuals (BTC, SOL, NEAR, ZEC — 5-minute chart)

| Setting | Value |
|---|---|
| Market profile | Auto-detect (dashboard should say *Crypto*); force *Crypto* if not |
| Sessions | All four on (reference windows); 7-day mode off at first |
| Entry mode | Breakout close baseline; compare Breakout + retest |
| Crypto block | ATR unit · min breakout 0.05 · retest tolerance 0.15 · stop *Opposite OR boundary* + 0.1 ATR · TP1 1 R · TP2 2 R · break-even after TP1 |
| Filters | Try volume > 1.2 × SMA 20 and HTF 60-min EMA 50, one at a time |
| Thin coins (NEAR, ZEC) | Prefer 5 m over 1 m; consider *Skip ranges with missing bars* on 1 m |
| Strategy → Properties | Commission: *% of order value*, your taker fee (e.g. 0.05). Slippage: ticks ≈ 0.01–0.03 % of price (BTC tick 0.1 → about 10–30 ticks). |
| Strategy → Backtest | Risk % of equity 0.5 · quantity step = exchange lot size · max leverage 3 |

---

## 4. Alerts and automation

Signals are generated **only on confirmed candle closes**. Each event triggers once,
after the candle has closed.

**Recommended:** a single alert with condition *Multi-Session ORB Pro* →
**Any alert() function call**. Choose *Message format* (Text or JSON) in the inputs
**before** creating the alert. Alerts keep the settings they were created with, so
re-create the alert after changing inputs.

Events: `ENTRY` (BREAKOUT / MOMENTUM / RETEST), `SETUP` (breakout waiting for a retest,
off by default), `WARNING` (FALSE_BREAKOUT), `TP1`, `EXIT` (TP2 / STOP /
BREAKEVEN_STOP / TIME_EXIT / BACK_INSIDE_RANGE / REPLACED).

Text example:
```
MS-ORB Pro | MNQ1! 5m | New York | ENTRY BREAKOUT LONG | Entry 21055.25 | SL 21009.75 | TP1 21100.75 (1R) | TP2 21146.25 (2R) | Price 21055.25 | ORH 21050.25 ORL 21010.25 | ID NY-20261124-1L
```

JSON example (for a webhook into a **paper-trading** bot such as AutoKel):
```json
{"source":"MS-ORB-Pro","bot":"AutoKel","schema":1,"paper_only":true,"event":"ENTRY","type":"BREAKOUT","side":"long",
 "symbol":"CME_MINI:MNQ1!","ticker":"MNQ1!","tf":"5","profile":"futures",
 "session":"NY","session_name":"New York","session_date":"2026-11-24","orh":21050.25,"orl":21010.25,
 "entry":21055.25,"stop":21009.75,"tp1":21100.75,"tp2":21146.25,"price":21055.25,
 "r":null,"tp1_r":1,"tp2_r":2,"tp1_pct":50,
 "signal_id":"NY-20261124-1L","bar_close_utc":"2026-11-24T14:55:00Z","bar_close_ms":1795532100000}
```
(The real message is a single line. The numbers above are illustrative.)

Bot-side guidance: de-duplicate on `signal_id` and `event`, reject messages whose
`bar_close_ms` is older than a few seconds/minutes, map `symbol` to your paper
instrument, and keep `paper_only` handling. TP1 / EXIT messages carry the same
`signal_id` as their entry. Webhook URLs require a paid TradingView plan. This script
only produces signals; it never sends or manages orders.

Classic alerts are also available (one condition per alert): *ORB bullish breakout*,
*ORB bearish breakout*, *ORB bullish retest*, *ORB bearish retest*,
*ORB false-breakout warning*, *ORB TP / SL / exit event*, *ORB any entry signal*. Their
messages use `{{plot("Sig entry")}}`-style placeholders from Data Window values.
Session numbers are 1 NY, 2 LDN, 3 CME, 4 TKY.

---

## 5. Backtesting with the strategy

* Same inputs and **the same engine code** as the indicator (verified by `check_shared.py`).
* **Execution:** the signal candle closes → market order fills at the **next candle's open**,
  plus the slippage set in Properties. Stop / TP1 / TP2 orders are the engine's levels.
  Limit orders must trade one tick through to fill (`backtest_fill_limits_assumption = 1`).
  Break-even uses the actual fill price.
* **Sessions to test:** `New York only`, `London only`, `CME Globex only`, `Tokyo only`, or
  `Use session toggles` (combined).
* **Session table** on the chart: trades, win %, profit factor, net P/L, closed-trade
  max drawdown, average R (P/L after commission ÷ initial risk) and skipped signals,
  for each session and in total. TradingView's own totals are shown underneath. The
  Strategy Tester's *Overview / Performance / List of Trades* remain the official
  report; it counts partial exits as separate trades.
* *One position at a time* (default) skips signals while a position is open. Those
  signals still appear in the indicator and are counted as **Skipped** here. That is
  the one intended difference between the two scripts.
* Properties to set for each market: commission type and value, slippage, initial
  capital, margin (default 5 %), and optionally the **Bar Magnifier** (premium plans),
  which uses lower-timeframe data to order fills inside a candle.
* Simulated results depend on history depth, data vendor, costs and fill assumptions.
  They are not live results. Prefer several months of data and look at each session
  separately before combining them.

---

## 6. Validating it yourself

### a) Compile
Paste each file into the Pine Editor and save. Any error message includes a line number.

### b) Sessions and daylight-saving changes
1. Dashboard → **Validation mode**. Each row then shows the current or next window
   start in **New York** and **UTC**.
2. Compare with the reference table. Generate it for any dates with:
   ```
   python3 pine/tools/engine_reference.py 2026-03-06 30
   ```
   Spot checks: London = 03:00 ET on 2026-03-06, **04:00 ET on 2026-03-09 … 03-27**,
   03:00 ET from 2026-03-30; **04:00 ET on 2026-10-26 … 10-30**, 03:00 ET from 2026-11-02.
   Tokyo = 19:00 ET (winter) / 20:00 ET (summer) on the previous NY date.
3. On a 5 m chart, hover over the window candles (e.g. 09:30, 09:35, 09:40 ET) and check
   that **NY ORH / ORL** in the Data Window equal their highest high and lowest low.
4. Holidays: on MNQ, 2026-11-26 (Thanksgiving) must have no NY range. 2026-11-27 must have one.
5. Change the chart's timezone setting: nothing should move, because session times
   don't depend on it.
6. Switch to a 10 m or 30 m chart: the dashboard should say those sessions are disabled.

### c) Signal timing
* Markers sit on the candle whose **close** confirmed the signal, never inside the box.
* In the strategy's *List of Trades*, the entry time is the **next** candle's open.
* Alert log timestamps are at the signal candle's close.

### d) Non-repainting
1. **Bar Replay**: replay a session candle by candle. A signal appears only when its candle
   completes. After replay ends, the markers are on the same candles as in history.
2. **Live check**: keep the chart open through a session, note the signals, then reload
   the page. They must be identical.
3. The forming box updates live **by design** until the window closes. Signals never use an
   unfinished range. Higher-timeframe data comes from closed candles only
   (`[1]` + `lookahead_on`).

### e) Indicator ↔ strategy parity
```
python3 pine/tools/check_shared.py          # both shared blocks must print OK
```
Load both scripts on one chart. Strategy triangles must line up with indicator
signals, except signals counted as Skipped.

### f) Offline tests (standard Python 3.9+)
```
python3 pine/tools/test_engine_reference.py -v      # 25 tests: DST, holidays, gaps, signals, exits
pip install pynescript                              # optional, for the linter
python3 pine/tools/lint_pine.py pine/*.pine         # slow (~1–2 min per file)
```
The reference model mirrors the Pine engine's logic. It tests the design, not
TradingView's runtime.

---

## 7. Known limitations

* **The strategy has not been compiled in TradingView yet** (see top).
* Holiday lists are hand-maintained text. Early closes don't matter (the open still happens).
* Engine entries use the signal candle close. The strategy fills at the next open, so its
  realised R differs slightly from the indicator's.
* With 1 futures contract there is no partial exit at TP1. TP1 then only moves the stop to break-even.
* Inside one candle the indicator assumes stop-before-target. TradingView's broker
  emulator uses its own open→high/low ordering. Bar Magnifier reduces the difference.
* TradingView strategies hold one net position. With *One position at a time* off,
  opposite-direction signals are skipped rather than netted.
* Heikin Ashi, Renko, Kagi, P&F, line-break and range charts are not supported (wick highs / lows are synthetic).
* **If TradingView reports “takes too long to execute” (RE10110):** turn off the sessions you
  don't trade (a disabled session skips the whole engine), then open the Pine Editor's
  **Profiler** mode and send me the slowest lines.
* Charts above the range length (e.g. 30 m for 15-min ranges) disable those ranges by design.

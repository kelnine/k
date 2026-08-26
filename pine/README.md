# Base HITS — TradingView indicator (Pine Script v6)

`base-hits.pine` is a single overlay indicator that puts the whole
session / liquidity-raid workflow on one chart.

## Install

1. TradingView → **Pine Editor** → *Open* → *New indicator*.
2. Paste the contents of [`base-hits.pine`](./base-hits.pine).
3. **Save**, then **Add to chart**.

Works on any symbol and any intraday timeframe (5m–15m is the sweet spot for
the session logic; the session stats need enough history, so let the chart load
a few hundred bars back).

## What it draws

| Piece | What it is |
| --- | --- |
| **Session boxes** | ASIA / LNDN / NYAM / NYPM shaded from the session's own high to its low, updated live while the session runs. |
| **Session levels** | When a session closes, its high and low are extended to the right as dotted lines with `ASIA High` / `NYPM Low` style labels. The line stops extending the moment price takes it out. |
| **HTF levels** | Previous day high/low + previous daily close (`PDH` / `PDL` / `Close`), previous week (`PWH` / `PWL`) and previous month (`PMH` / `PML`). Each period draws a fresh segment, so history stays stepped. |
| **Session opens** | The price at 09:30 (`NY Open`), 12:00 (`Midday`) and 00:00 (`Midnight`), held for the day, with a dotted vertical divider on the bar that stamps each one. |
| **Midpoints** | `PDM` / `PWM` / `PMM` — the middle of the previous day's, week's and month's range. |
| **Dealing range** | The last confirmed swing high to swing low, split at equilibrium: red tint above (premium), green tint below (discount), with `0.75` / `EQ` / `0.25` marked. A second, shorter-pivot range can be nested inside it. |
| **Trend cloud** | A supertrend line with an ATR-deep band filled behind it — green under price in an uptrend, pink above price in a downtrend. |
| **Bias of the day** | One direction per day. A buy day only ever prints `BUY LR`, a sell day only ever prints `SELL LR` — everything against the bias is suppressed. |
| **`SELL LR` / `BUY LR`** | Liquidity-raid signals: price trades *through* a resting level and closes back on the other side of it, **in the direction of the day's bias**. |
| **Trade projection** | On a signal, a red risk box (entry → stop) and a green reward box (entry → target) extend forward until the trade resolves; the box then freezes at the bar that hit, labelled `SL`, `TP` or `BE`. |
| **Partial target** | A dashed `TP1` line inside the reward box at *Partial target at* R (1R by default) — where you'd take a piece off. It ticks over to `TP1 ✓` when price reaches it. |
| **Breakeven** | Once the trade is up *Move stop to breakeven at* R (1R by default), the stop snaps to entry — the risk box collapses to a grey line and the trade can no longer lose. Breakevens are counted separately from wins and losses. |
| **Projected HTF candle** | The higher-timeframe candle currently being built (15m by default) drawn to the right of the last bar, with its own countdown underneath — the `15m 02:08` block. |
| **Stats table** | Per session and per period: average range, and how often that high / that low is swept afterwards. |
| **Countdown** | Timeframe + time remaining on the current bar, pinned next to price. |

## Bias of the day

The bias is set **once per day** and then locked until the next day, so the
indicator only ever signals one direction on a given day. `Bias label on chart`
shows it next to price (green `BUY BIAS` / red `SELL BIAS`) and the table's
corner cell mirrors it — hover either for the reason it was set.

| Mode | How the day gets its direction |
| --- | --- |
| **Sweep of a session** *(default)* | Whichever side of the chosen range gets grabbed first decides the day: the **low** taken → buy day, the **high** taken → sell day. Source is selectable (ASIA / LNDN / NYAM / NYPM / prior day); the range must have closed inside the current day, so yesterday's Asia never sets today's bias. If both sides get swept on the same bar, the close inside the range breaks the tie. |
| **Prior-day equilibrium** | Locked on the day's first bar: trading above the midpoint of the previous day's range → buy day, below → sell day. |
| **Prior-day direction** | Previous daily candle closed up → buy day, closed down → sell day. |
| **Daily EMA trend** | Previous daily close above the daily EMA → buy day, below → sell day. |
| **Manual** | You call it: *Buy only*, *Sell only*, or *Both*. |

Until the bias is set — before the session has been swept, typically — signals
are held back. Flip `Allow signals before the bias is set` if you would rather
see both sides in that window. When the raid that sets the bias *is* the entry,
it still counts: the bias is evaluated before the signal on the same bar, so
the sweep bar can print its `LR` label.

## How a liquidity raid is defined

A level is "resting liquidity" until it is taken. The three pools are
selectable independently:

* **Session highs / lows** — the last completed ASIA / LNDN / NYAM / NYPM
  extreme, while it is still unswept.
* **PD / PW / PM levels** — only the *first* sweep of each level in its period
  counts, so PDH does not fire ten times in one day.
* **Swing pivots** — `ta.pivothigh` / `ta.pivotlow` of the configured length;
  a pivot leaves the pool once price trades past it.

A **SELL LR** prints when, on one bar: `high > level` **and** `close < level`,
the upper wick is at least *Min sweep wick %* of the bar's range, the bar
closes down (*Require rejection close*), the cooldown since the last signal has
elapsed, **the day's bias is a sell bias**, and — optionally — the trend cloud
is bearish. **BUY LR** is the mirror image. When both sides trigger on the same
bar, the bias breaks the tie (the trend cloud does it if there is no bias yet).

Stop placement uses the swept extreme (`max(high, level)` for a sell) plus an
ATR buffer; the target is a fixed R multiple of that risk.

`Only sell in premium, only buy in discount` (off by default) adds the dealing
range as a location filter on top of the bias: sells only above equilibrium,
buys only below it.

## Reading the stats table

* **Range** — average high-to-low range of the last *N* occurrences of that
  session/period (`Stat sample size`, default 20). Hover a cell for the sample
  count actually collected so far.
* **High** — of those occurrences, the share whose **high** was traded through
  afterwards (before the same session came around again / before that period
  rolled over).
* **Low** — same for the **low**.

A high `High` percentage means that level rarely survives — it is a magnet, not
a wall. Both columns start empty and fill in as the chart replays history, so
scroll back far enough for the numbers to settle.

The last row (`LR`) tallies how the indicator's own projected trades resolved —
wins, losses, and breakevens. Hover it for the win rate excluding breakevens.

## Alerts

Two alert conditions are exposed — **SELL LR** and **BUY LR** — plus dynamic
`alert()` calls, so *Any alert() function call* works too. Both fire once per
bar close.

## Defaults worth changing

* **Timezone / session times** default to `America/New_York` with
  Asia `2000-0000`, London `0200-0500`, NY AM `0930-1200`, NY PM `1330-1600`.
  Adjust to your instrument's killzones.
* **Bias mode** defaults to *Sweep of a session* off the **ASIA** range — the
  classic "they grabbed the Asia low, so we're only buying today" read. Switch
  the source or the mode if your day starts somewhere else.
* **Require trend alignment** is off by default — it's a second, intrabar
  filter on top of the daily bias, not a replacement for it.
* **Reward : risk** defaults to 2.0; **Project forward** controls how far the
  boxes run ahead of price. **Partial target at** and **Move stop to breakeven
  at** both default to 1R, so the usual sequence — take a piece at 1R, stop to
  entry, let the rest run — is what you get out of the box. Set either to 0 to
  turn it off.
* **Nested range** is off by default. Turn it on for the second, tighter
  premium/discount read inside the bigger one.
* **Projected HTF candle** defaults to 15m. On a 5m chart that gives the
  familiar "three of these make the candle I actually care about" read; set the
  timeframe, its distance from price and its width to taste.

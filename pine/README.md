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
| **Trend cloud** | A supertrend line with an ATR-deep band filled behind it — green under price in an uptrend, pink above price in a downtrend. |
| **`SELL LR` / `BUY LR`** | Liquidity-raid signals: price trades *through* a resting level and closes back on the other side of it. |
| **Trade projection** | On a signal, a red risk box (entry → stop) and a green reward box (entry → target) extend forward until the trade resolves; the box then freezes at the bar that hit, labelled `SL` or `TP`. |
| **Stats table** | Per session and per period: average range, and how often that high / that low is swept afterwards. |
| **Countdown** | Timeframe + time remaining on the current bar, pinned next to price. |

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
elapsed, and — optionally — the trend cloud is bearish. **BUY LR** is the
mirror image. When both sides trigger on the same bar, the one aligned with the
trend wins.

Stop placement uses the swept extreme (`max(high, level)` for a sell) plus an
ATR buffer; the target is a fixed R multiple of that risk.

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

The last row (`LR`) tallies how the indicator's own projected trades resolved:
wins, losses, and win rate at the configured R:R.

## Alerts

Two alert conditions are exposed — **SELL LR** and **BUY LR** — plus dynamic
`alert()` calls, so *Any alert() function call* works too. Both fire once per
bar close.

## Defaults worth changing

* **Timezone / session times** default to `America/New_York` with
  Asia `2000-0000`, London `0200-0500`, NY AM `0930-1200`, NY PM `1330-1600`.
  Adjust to your instrument's killzones.
* **Require trend alignment** is off by default — turn it on to only take raids
  in the direction of the cloud.
* **Reward : risk** defaults to 2.0; **Project forward** controls how far the
  boxes run ahead of price.

# BASE HITS — TradingView indicator (Pine Script v6)

One overlay: sessions, liquidity raids, a daily bias, and the session stats
table. `base-hits.pine` is the whole thing.

## Install

1. TradingView → **Pine Editor** → *Open* → *New indicator*.
2. Delete what's there, paste the **entire** contents of
   [`base-hits.pine`](./base-hits.pine).
3. **Save**, then **Add to chart**.

Built around a 5m chart with a 15m projected candle. Let the chart load a few
hundred bars back so the stats table has samples to average.

## What it replaces

It rolls one stack into a single script:

| Original | What it contributed |
| --- | --- |
| **ICT Killzones + Pivots** | session boxes, session highs/lows, the stats table |
| **ICT Pro Tools** | the day/week/month levels and the liquidity-raid reads |
| **HTF Candle** | the developing higher-timeframe candle beside price |
| **VWAP** | anchored VWAP with σ bands |
| **Volume Profile (200 × 200)** | the volume histogram, POC and value area |

## What's on the chart

| Piece | What it is |
| --- | --- |
| **Session shading** | ASIA / LNDN / NYAM / NYPM shaded from the session's own high to its low, growing as the session runs, plus a dotted vertical line on each session open. |
| **Session levels** | When a session closes, its high and low extend right as dotted lines labelled `ASIA High`, `NYPM Low` and so on. The line stops the moment price takes it. |
| **Horizontal levels** | `PDH` `PDL` `PDM` `Close` (red), `PWH` `PWL` `PWM` (blue), `PMH` `PML` `PMM` (purple, off by default), and `NY Open` / `Midday` / `Midnight` (black). Each period starts a new segment, so history stays stepped. |
| **Trend cloud** | Supertrend line with an ATR-deep band filled behind it — green in an uptrend, pink in a downtrend — plus the dotted parabolic trail. |
| **`SELL LR` / `BUY LR`** | Yellow raid labels: price sweeps resting liquidity and closes back on the other side of it, **only in the direction of the day's bias**. |
| **Trade projection** | Red risk box (entry → stop), green reward box (entry → target), a dashed `TP1` partial line, and the stop snapping to entry at breakeven. Freezes at the bar that resolves it, labelled `TP` / `SL` / `BE`. |
| **Stats table** | Per session and per period: average range, how often that high gets taken, how often that low gets taken. The corner cell shows the day's bias; the bottom row tallies W / L / BE. |
| **HTF candle** | The 15m candle currently being built, parked to the right of price with its countdown. |
| **VWAP** | Anchored VWAP (day / week / month) with 1σ and 2σ bands and a filled 2σ envelope. |
| **Volume profile** | The last 200 bars bucketed into rows and drawn from the right edge: POC in orange, the 70% value area shaded, VAH/VAL/POC extended back across the lookback. |

## Bias of the day

Set **once per day**, then locked — so a buy day only ever prints `BUY LR` and a
sell day only ever prints `SELL LR`.

| Mode | How the day gets its direction |
| --- | --- |
| **Session sweep** *(default)* | First side of the chosen range to get grabbed decides it: **low taken → buy day**, **high taken → sell day**. Source is selectable (ASIA default). The range must have closed inside the current day, so yesterday's Asia can't set today's bias. |
| **Prior-day equilibrium** | Above the midpoint of yesterday's range → buy day, below → sell day. |
| **Prior-day direction** | Yesterday closed up → buy day, closed down → sell day. |
| **Manual** | Buy only / Sell only / Both. |

The bias is evaluated *before* signals on the same bar, so the raid that sets
the bias can still be the entry. Until it's set, signals are held back — flip
`Allow signals before the bias is set` if you'd rather see both sides.

## What counts as a raid

Three liquidity pools, each switchable:

* **Session highs / lows** — the last completed session extreme, while unswept.
* **PD / PW / PM levels** — only the first sweep of each per period.
* **Swing pivots** — `pivothigh` / `pivotlow` of the set length; a pivot leaves
  the pool once price trades past it.

`SELL LR` prints when one bar takes out a level (`high > level`) and closes back
under it, the upper wick is at least *Min sweep wick %* of the bar, the bar
closes down, the cooldown has passed, and the day's bias is sells. `BUY LR` is
the mirror.

## Reading the table

* **Range** — average high-to-low range of that session/period across all the
  history the chart has loaded (hover a cell for the sample count).
* **High** — how often that high gets traded through afterwards.
* **Low** — same for the low.
* **LR row** — how the projected trades resolved: wins, losses, breakevens.

## Alerts

`SELL LR` and `BUY LR` as alert conditions, plus `alert()` calls so *Any
alert() function call* works. Once per bar close.

## Tuning the volume profile

`Lookback` and `Rows` default to 200 × 80. Rows can go to 200, but every row is
a box and TradingView caps a script at 500 of them, so a high row count eats
the budget the session boxes also draw from — drop it if older session shading
starts disappearing. `Width` and `Gap` control how far right of price it sits.

## Not in here

The target/stop boxes with dollar amounts in his screenshots are the manual
**Long/Short Position** drawing tool — a script can't produce those numbers
(no order size or account currency). The risk/reward projection here is the
automated stand-in.

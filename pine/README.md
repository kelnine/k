# Orderflow Footprint — TradingView indicator

`orderflow-footprint.pine` is the [OrderflowChart](https://github.com/harveysp/OrderflowChart)
footprint rebuilt as a Pine Script v6 indicator, so it runs on a real
TradingView chart rather than in a notebook.

## Install

1. Open a chart on tradingview.com → **Pine Editor** (bottom panel).
2. Paste the contents of `orderflow-footprint.pine`, replacing the template.
3. **Save**, then **Add to chart**.
4. Start on a **15m chart or higher** of a liquid symbol. Use the gear icon to tune.

## Plan gates (read this first)

Two things on TradingView are gated to **Premium and higher**, and both matter here:

- **Seconds-based intrabars.** Requesting one on a lower plan stops the script
  with `Runtime error: RE10063`. So "Allow seconds-based intrabars" is **off by
  default** and the automatic choice uses 1-minute intrabars, which every plan
  can request.
- **`request.footprint()`**, the API that returns the exchange's real bid/ask
  rows, needs the same tier.

With 1-minute intrabars, the resolution of the footprint is simply how many
minutes are in a bar — five on a 5m chart, sixty on a 1h chart. The table's
top-left cell shows what you are actually getting (`1 · 15/bar`), and the row
count is capped to the intrabar count so you never get more rows than there is
data to fill them. **On a non-Premium plan, 15m and higher is where this gets
useful.**

## What it draws

| Element | Meaning |
| --- | --- |
| Cell colour | Diagonal imbalance `(bid[row] − ask[row above]) / (bid + ask)` on the `icefire_r` ramp — blue where sellers dominate the diagonal, red/orange where buyers do |
| `bid × ask` | Volume that traded into the bid (left) and into the ask (right) |
| Purple bar | Volume profile for the row, scaled against the bar's heaviest row |
| Yellow outline | Point of control — the row with the most volume |
| Cyan / orange outline | Rows past the imbalance threshold |
| Bottom table | `roc`, `volume`, `cum delta` (rolling 10-bar sum of delta), `delta`, coloured red→green through `tanh` |

## The honest limitation

**Pine cannot see who was the aggressor.** TradingView does not expose the
trade-by-trade buy/sell flag to scripts, so this indicator estimates the split
from lower-timeframe candles: an intrabar closing up puts its volume on the ask,
closing down puts it on the bid, and an unchanged close falls back to the tick
rule. That is how every non-native footprint script on TradingView works, and it
is close but not identical to exchange-reported bid/ask volume.

Finer intrabars are more accurate. `Auto` picks one from the chart timeframe,
staying on minutes unless you opt into seconds.

### Getting exact data instead

TradingView shipped `request.footprint()` for Pine in **January 2026**, which
returns the exchange's own footprint rows (real buy/sell volume, POC, value
area, imbalances). It needs a **Premium plan or higher** — the same tier as
seconds-based intrabars, so if `RE10063` fires on this script, that API is out
of reach too. Swapping it in only touches the aggregation block — the drawing,
colours and table stay as they are.

## Other limits worth knowing

- **500 drawing objects per script.** Cells are drawn newest-first until the
  budget runs out, so raising `Footprint bars` or turning on the volume profile
  reduces how far back the footprint reaches.
- **Intrabar history is capped** (100k lower-timeframe bars on most plans), so
  older bars simply have no footprint.
- Cells are boxes, which draw over the candles — keep some `Cell transparency`
  if you want to see the price action through them.
- Columns are positioned in time, half a bar either side of each candle. On
  symbols with session gaps the bar next to a gap can look slightly wide.

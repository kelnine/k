# Orderflow Footprint — TradingView indicator

`orderflow-footprint.pine` is the [OrderflowChart](https://github.com/harveysp/OrderflowChart)
footprint rebuilt as a Pine Script v6 indicator, so it runs on a real
TradingView chart rather than in a notebook.

## Install

1. Open a chart on tradingview.com → **Pine Editor** (bottom panel).
2. Paste the contents of `orderflow-footprint.pine`, replacing the template.
3. **Save**, then **Add to chart**.
4. Start on a **5m or 15m chart** of a liquid symbol. Use the gear icon to tune.

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

Finer intrabars are more accurate. `Auto` picks one from the chart timeframe;
second-based intrabars need a paid plan.

### Getting exact data instead

TradingView shipped `request.footprint()` for Pine in **January 2026**, which
returns the exchange's own footprint rows (real buy/sell volume, POC, value
area, imbalances). It needs a **Premium plan or higher**. Swapping it in only
touches the aggregation block — the drawing, colours and table stay as they are.

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

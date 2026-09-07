# Pine Script

`kcharts-profile.pine` is the KCharts chart template ported to TradingView:
visible-range volume profile, the EMA pair, and supply/demand bands, in one
overlay indicator.

## Install

1. Open any chart on TradingView → **Pine Editor** (bottom panel).
2. Paste the contents of `kcharts-profile.pine`, replacing the starter script.
3. **Save** (give it a name), then **Add to chart**.
4. Optional: open the indicator's settings → **Defaults → Save as default**, and
   add it to a chart layout you can reuse across symbols.

Requires Pine v6, which is standard on TradingView — no paid plan needed for the
indicator itself (the number of indicators per chart is what plan tiers limit).

## What it draws

| Element | Detail |
| --- | --- |
| Volume profile | Volume bucketed by price across the **visible** bars, each row split into up volume (close ≥ open) and down volume. Recomputes when you scroll or zoom. |
| Value area | The rows holding 70 % of volume around the POC, coloured white/blue; the wings outside it green/orange. |
| POC | Heaviest row, drawn across the chart and extended right, with a price label. |
| VAH / VAL | Off by default — dotted teal/orange lines when enabled. |
| EMAs | 50 red, 200 green by default. |
| Zones | Supply and demand bands from confirmed pivots, extended right until price *closes* through them. |
| Stats | POC / VAH / VAL table, top-right. |

## Inputs that match the reference charts

- Timeframe **4h** (1D for the higher-timeframe reads), Binance perpetuals.
- Profile: rows `80`, width `30 %`, value area `70 %`, POC line on, VAH/VAL off.
- EMAs: fast `50`, slow `200`.
- Zones: pivot strength `10`, 3 per side.

## Deliberately not ported

- **Position boxes and measured moves.** TradingView already has these as native
  drawing tools — *Long Position*, *Short Position* and *Price Range* — and they
  are interactive there in a way a Pine script can't be. Use those.
- **Profile-derived alerts.** The profile follows each viewer's visible range, so
  an alert on "price crossed the POC" would fire off a different level depending
  on how the chart is scrolled. Alerts are limited to the stable, series-based
  conditions: EMA crosses and price entering a supply/demand band.

## Behaviour worth knowing

- **The profile recalculates as you scroll.** That is the point of a visible-range
  profile, but it means the POC moves when the window changes. Anchor a level you
  intend to trade by dragging a horizontal line onto it.
- **Boxes render above candles in Pine**, unlike the KCharts engine where the
  profile sits behind them. The row colours therefore ship at 25 % transparency;
  raise it in the settings if you want the bars fainter still.
- **Zones appear `pivot strength` bars late**, since a pivot is only confirmed
  once that many bars have printed either side of it.
- **`Max bars scanned`** (default 1500) caps how far back the profile looks when
  the whole history is on screen. Raise it for long visible ranges on low
  timeframes; lower it if the script feels slow.

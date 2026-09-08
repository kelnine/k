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
| Volume profile | Volume bucketed by price, each row split into up volume (close ≥ open) and down volume. The range it measures is set by **Profile range** — see below. |
| Value area | The rows holding 70 % of volume around the POC, coloured white/blue; the wings outside it green/orange. |
| POC | Heaviest row, drawn across the chart and extended right, with a price label. |
| VAH / VAL | Off by default — dotted teal/orange lines when enabled. |
| EMAs | 50 red, 200 green by default. |
| Zones | Supply and demand bands from confirmed pivots, extended right until price *closes* through them. |
| Previous session | POC / VAH / VAL of the session that has already closed, drawn as fixed lines that never move. |
| Stats | POC / VAH / VAL table, top-right. |

## Profile range — which one to use

| Mode | Measures | POC behaviour |
| --- | --- | --- |
| **Session** (default) | Today's bars only | Holds still as you scroll. Grows through the day as volume accumulates. |
| **Fixed bars** | The last N bars | Holds still as you scroll. Rolls forward one bar at a time. |
| **Visible range** | Whatever is on screen | Moves whenever you scroll or zoom — this is what TradingView's VPVR does, and it is only useful while you keep the window fixed. |

If you want a level that does not move at all, use the **previous session**
lines: that session is closed, so its POC/VAH/VAL are final.

Whichever mode is active, the histogram is drawn from the left edge of the
screen, so a session that starts off-screen still shows its bars.

## Inputs that match the reference charts

- Timeframe **4h** (1D for the higher-timeframe reads), Binance perpetuals.
- Profile: range `Visible range` for the screenshot look, rows `80`, width `30 %`,
  value area `70 %`, POC line on, VAH/VAL off.
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

- **Only `Visible range` recalculates as you scroll.** Session and Fixed bars hold
  their levels. If you trade off a developing POC in any mode, remember it can
  still drift as new volume prints — drag a horizontal line onto it to freeze it.
- **Boxes render above candles in Pine**, unlike the KCharts engine where the
  profile sits behind them. The row colours therefore ship at 25 % transparency;
  raise it in the settings if you want the bars fainter still.
- **Zones appear `pivot strength` bars late**, since a pivot is only confirmed
  once that many bars have printed either side of it.
- **`Max bars scanned`** (default 1500) caps how far back the profile looks when
  the whole history is on screen. Raise it for long visible ranges on low
  timeframes; lower it if the script feels slow.

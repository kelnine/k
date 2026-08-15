# Order Flow Desk — Pine Script v6

`order-flow-desk.pine` is a single TradingView indicator that puts the whole order-flow
read on one price pane: volume profile, VWAP with deviation bands, aggressor delta and
volume bubbles, a purple liquidity heat map, resting-liquidity levels, gamma/options
strike levels, a prints tape, and a dashboard.

Paste it into Pine Editor → Save → Add to chart. No dependencies.

## What is real and what is inferred

Pine only receives OHLCV bars. It has **no** access to the options tape, to an options
chain (so no computed GEX), or to level-2 depth. Every module below is labelled by which
side of that line it sits on, and the script's header repeats it.

| Module | Basis |
| --- | --- |
| Volume profile · POC / VAH / VAL / HVN / LVN | **Observed** — bar volume distributed across each bar's range |
| VWAP + 1/2/3σ bands, previous-anchor VWAP | **Observed** |
| Prints tape | **Observed** — large intrabar prints in the underlying |
| Aggressor delta, CVD, volume bubbles | **Inferred** — intrabar tick rule, or a close-position estimate when intrabar data is unavailable |
| Liquidity heat map | **Inferred** — traded volume-at-price per time slice with recency decay, *not* book depth |
| Absorption shelves, liquidity pools, sweeps | **Inferred** — the passive-liquidity footprint price action does expose |
| Gamma flip / call wall / put wall / strikes | **External** — you type the levels in; the script draws, tracks, shades and alerts on them |

The gamma module behaves like a real GEX overlay once levels are entered — zones, magnet
alerts, regime shading, nearest-level distance. Only the chain math happens outside Pine,
in whatever options provider you already run on the second monitor.

## Modules

**① Flow engine.** Splits each bar's volume into aggressive buying vs selling using
lower-timeframe bars (`request.security_lower_tf`). Resolution is `Auto` by default and
picks a sub-bar timeframe from the chart timeframe; an invalid or unavailable one is
ignored rather than raising, and the script falls back to the close-position estimate —
the dashboard's *Flow source* row always tells you which is live. Drives delta, CVD, and
the volume bubbles (radius = relative volume, colour = aggressor side, hover for the
buy/sell/delta breakdown).

**② Volume profile.** Session, fixed-lookback, or visible-range window. Rows split into
buy/sell volume, POC highlighted, value area shaded and extendable across the window,
HVN/LVN tagged. Anchors to the right of the last bar or to the left of the window.

**③ VWAP.** Session/week/month/quarter/year anchor, three σ bands with fills, and the
previous anchor's closing VWAP carried forward as a step line.

**④ Liquidity heat map.** A price × time grid behind the candles. Each cell is the volume
that traded in that price row during that time slice, decayed by column age, normalised
against the hottest cell, and drawn in the purple palette. Controls: rows, columns, bars
per column, decay, contrast, noise floor, transparency, and the three gradient stops. Grid
size is auto-clamped to stay inside TradingView's 500-object budget.

**⑤ Book proxy.** Two things Pine *can* see about passive liquidity: absorption shelves
(high relative volume plus a compressed range means aggression met resting size — the
shelf marks the level and stays live until price closes through it), and liquidity pools
(equal highs/lows within an ATR tolerance, thickening as they get retested, deleted on a
sweep or an accepted break, with sweep markers).

**⑥ Gamma / options levels.** Gamma flip, call wall, put wall with configurable zone
width, a free-form `price:label` list for anything else your provider gives you
(`6120:HVL, 6150:1D GEX, 6200`), an auto strike grid at any spacing, magnet-distance
detection, and background shading for the long-gamma / short-gamma regime.

**⑦ Tape.** Last N prints above a size threshold: time, price, size, side. Sourced from
intrabar data when available, otherwise one row per outsized bar.

**⑧ Dashboard.** VWAP and σ distance, POC, value area, bar delta, CVD, relative volume,
profile buy/sell split, gamma regime, nearest level and its distance, live pool counts,
and the flow-source status.

## Alerts

VWAP cross · POC test · value-area breakout / breakdown · delta flip on volume ·
absorption · buy-side and sell-side sweeps · gamma wall touch · gamma flip cross.

## Notes on performance

The profile, heat map and gamma levels redraw on the last bar on every tick — that is the
only way TradingView keeps realtime drawings alive through bar rollback. If it feels heavy
on a deep chart, reduce heat-map columns or profile rows first; both dominate the cost.

Symbols without volume (many indices and FX feeds) will show `no volume on this symbol` in
red on the dashboard — the profile, heat map and delta are meaningless there, so use a
futures or spot proxy instead.

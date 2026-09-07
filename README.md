# KCharts

A fast, free, open charting platform — a TradingView-style experience built on a
fully custom canvas rendering engine, with no third-party charting library.

![stack](https://img.shields.io/badge/stack-TypeScript%20%C2%B7%20React%20%C2%B7%20Vite-blue)

## Features

- **Custom canvas engine** — candlesticks, volume, multi-pane layout, HiDPI-aware,
  renders only the visible range so it stays smooth with deep history.
- **Trading interactions** — drag to pan, scroll to zoom (anchored at the cursor),
  double-click to reset, crosshair with OHLC legend, infinite history loading as
  you pan back.
- **Footprint (orderflow) charts** — a full bid/ask footprint built from raw
  tick data: every candle splits into price rows showing the volume that traded
  into the bid vs. the ask, tinted by diagonal imbalance, with a per-bar volume
  profile, the point of control, and a `roc / volume / cum delta / delta`
  parameters strip underneath. Modelled on
  [OrderflowChart](https://github.com/harveysp/OrderflowChart), rendered live on
  the same canvas engine instead of Plotly.
- **Indicators** — MA 20/50/200, EMA 21, Bollinger Bands, daily-anchored VWAP
  (overlays) plus RSI and MACD in their own synced panes.
- **Phantom Flow SMC** — a from-scratch Smart Money Concepts overlay: swing
  structure (HH/HL/LH/LL), BOS/CHoCH market-structure breaks, order blocks and
  fair-value-gap zones (auto-extended until mitigated/filled), and equal-high/low
  liquidity pools, with a live trend read-out in the legend.
- **Drawing tools** — trendlines, horizontal levels, Fibonacci retracements, and
  text notes. Select, drag, re-anchor endpoints, delete with `Del`. Saved per
  symbol in `localStorage`.
- **Multi-chart layouts** — 1 / 2 / 4 chart grids with an active-chart concept;
  symbol search, timeframe, and indicators apply to the focused chart.
- **Watchlist** — live prices with up/down flashes and 24 h change.
- **Real-time streaming** — WebSocket candle updates with automatic reconnect.
- **Pluggable data layer** — everything talks to a small `DataAdapter` interface
  (`src/data/types.ts`). Ships with:
  - `BinanceAdapter` — free, keyless spot market data (REST + WebSocket),
    including aggTrade tick data for footprints
  - `DemoAdapter` — deterministic synthetic feed (candles *and* trades) used
    automatically when the exchange is unreachable, so the app always works

## Footprint charts

Switch the active chart to **▦ Footprint** in the toolbar. `Rows` sets the price
row height (`fine` … `4×`) and `POC` outlines each bar's point of control.

How a bar is built:

- Trades come from Binance `aggTrades` — paged backwards by trade id rather
  than by time window, which is the only way to read a busy symbol without
  silently truncating. `isBuyerMaker` decides the side: an aggressive sell
  lands in **bid**, an aggressive buy in **ask**.
- Prints are bucketed onto a fixed price grid, so rows line up across bars. Row
  height is auto-picked to split a typical candle into ~14 rows, snapped to the
  exchange's `PRICE_FILTER` tick.
- Cell colour is the **diagonal imbalance** `(bid[p] − ask[p+1row]) / (bid[p] +
  ask[p+1row])` on the `icefire_r` ramp — blue where sellers dominate the
  diagonal, red/orange where buyers do — matching the reference chart.
- The strip underneath shows `roc`, `volume`, `cum delta` (rolling 10-bar sum of
  delta) and `delta`, coloured red→green through `tanh`.

Tick history is capped per load, so older bars in the window may have no
footprint; the chart says how many bars it could build. Drag to pan, wheel to
zoom, drag the price axis to stretch it, double-click to reset.

## Run it

```sh
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production bundle in dist/
```

## Adding a data source

Implement the four-method `DataAdapter` interface in `src/data/` (search,
historical candles, candle stream, ticker stream) and wire it into
`resolveAdapter()` in `src/data/index.ts`. Nothing else in the app needs to
change — the engine and UI are data-source agnostic.

To light up footprint charts as well, also implement the optional `TradeSource`
interface (recent trades, trade stream, price tick). Adapters without it keep
working; the footprint view just reports that the feed has no tick data.

## Architecture

```
src/
  data/        DataAdapter + TradeSource interfaces, Binance + demo adapters
    orderflow.ts footprint aggregation: rows, imbalance, delta, POC
  engine/      custom canvas chart engine (no chart libraries)
    chart.ts     panes, scales, interaction, rendering, streaming
    footprint.ts footprint renderer: heat cells, profile, parameters strip
    colorscale.ts icefire_r / RdYlGn ramps
    drawings.ts  drawing tools: render + hit-testing
    utils.ts     axis ticks, price/time formatting
  indicators/  pure-function indicator library + registry
  ui/          React shell: toolbar, layouts, watchlist, search
```

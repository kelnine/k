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
  - `BinanceAdapter` — free, keyless spot market data (REST + WebSocket)
  - `DemoAdapter` — deterministic synthetic feed used automatically when the
    exchange is unreachable, so the app always works

## Run it

```sh
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production bundle in dist/
```

## TradingView indicator

`pine/phantom-flow-desk.pine` is a standalone Pine Script v6 indicator for
TradingView (it is not used by the KCharts app). One script draws a full desk
layout:

- **On the chart** — range volume profile with buy/sell split, POC and value
  area, shaded range with high/low, auto trendlines with break markers, a moving
  average, confluence signals and a dashboard.
- **In its own pane** — momentum histogram with squeeze dots, WaveTrend and
  Stoch RSI, stacked as three bands.

To use it: open the Pine Editor in TradingView, paste the file's contents,
then **Add to chart**.

## Adding a data source

Implement the four-method `DataAdapter` interface in `src/data/` (search,
historical candles, candle stream, ticker stream) and wire it into
`resolveAdapter()` in `src/data/index.ts`. Nothing else in the app needs to
change — the engine and UI are data-source agnostic.

## Architecture

```
src/
  data/        DataAdapter interface, Binance + demo adapters
  engine/      custom canvas chart engine (no chart libraries)
    chart.ts     panes, scales, interaction, rendering, streaming
    drawings.ts  drawing tools: render + hit-testing
    utils.ts     axis ticks, price/time formatting
  indicators/  pure-function indicator library + registry
  ui/          React shell: toolbar, layouts, watchlist, search
```

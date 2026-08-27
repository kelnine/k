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
- **OTE Sniper** — finds the last confirmed impulse leg, auto-anchors a fib
  (0 at the leg's terminal extreme, 1 at its origin), and flags the
  0.62 / 0.705 / 0.79 OTE band. Where an unfilled FVG from that same leg
  overlaps the band, the overlap becomes the entry zone, drawn with entry /
  stop / target and live R:R, then tracked through tapped → target or stopped.
  Shipped for TradingView too — see `pine/ote-sniper.pine`.
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

## TradingView script

`pine/ote-sniper.pine` is a standalone Pine v6 indicator implementing the same
OTE Sniper rules. Paste it into TradingView's Pine Editor, *Add to chart*, and
it draws the FVG, the fib ladder, the entry zone and the risk/reward projection
on any symbol and timeframe. It ships four alerts — new setup, price entered
the zone, target hit, stopped out — available both as `alert()` messages
("Any alert() function call") and as named `alertcondition` entries.

Only the live setup is drawn in full — FVG box, fib ladder, entry zone and the
risk/reward projection, which sits in the empty space to the right of price so
it never covers candles. Resolved setups keep just their zone, dimmed and
colour-coded by outcome (*Past setups*: `Faded` / `Labelled` / `Hide`), which
keeps an intraday chart readable. The info panel corner is configurable for
mobile.

Three controls handle legibility — **Text size** (bump it to Large on a phone),
**Zone fill strength**, and **Line width**. When there is no live setup the info
panel names the gate that rejected the last impulse leg, rather than leaving you
to guess whether the script is working.

Defaults are ICT-style: swing strength 5, an impulse leg of at least 2× ATR(14),
FVG confluence required, stop beyond the leg origin, target at fib 0. Turn off
*Require FVG confluence* to trade the raw OTE band, or switch *Target from* to
*Risk multiple* for a fixed-R target instead of a full retest of the leg.

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
    smc.ts       Phantom Flow: structure, order blocks, FVGs, liquidity
    ote.ts       OTE Sniper: impulse leg -> fib OTE + FVG entry zones
  ui/          React shell: toolbar, layouts, watchlist, search
```

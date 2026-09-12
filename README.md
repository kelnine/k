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
- **Goldbach PO3** — power-of-three dealing ranges with the Goldbach partition
  drawn across them: `0.03 RB`, `0.11 OB`, `0.17 FV`, `0.29 LV`, `0.41 BR`,
  `0.47 MB`, `0.5 EQ` and their premium mirrors, plus the ±0.111 extensions,
  for two nested ranges at once (the way 81 and 243 nest on NQ). Ranges anchor
  to multiples of their own size, so the levels are the same for everyone
  looking at the instrument — no swing picking. A premium/discount column sits
  in the right-hand gutter.
- **Frankenstein AI** — a ten-limb ensemble that scores every bar and paper-trades
  its own signal. Market structure, order blocks, fair-value gaps, the trend
  stack, momentum, VWAP, liquidity sweeps, the fib pocket, volume thrust and the
  Goldbach range position each vote independently; the votes are blended and then throttled by a
  volatility/agreement gate, and the gated score drives a simulated trader that
  sizes by conviction, scales out at 1R/2R and trails the runner. By default it
  does not chase: it rests a limit order on the nearest Goldbach level price has
  to come back for, and pulls it if the signal flips. Entries and
  exits are drawn on the chart as `qty @ price` tickets with their risk/reward
  boxes, alongside a live-zone overlay, a fib ladder and a price-level heat
  ribbon. **Simulated fills only — no broker is connected.**
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

## The Frankenstein model

```
src/model/
  goldbach.ts   PO3 dealing ranges + the Goldbach partition (pure arithmetic on
                price: no swings, no lookback, nothing to confirm)
  features.ts   causal feature layer — EMAs, RSI, ATR, MACD, VWAP, swings,
                order blocks, FVGs, liquidity pools, impulse legs. Every
                derived object records the bar it first becomes *knowable* at,
                so a swing pivot is invisible until its confirmation bars pass.
  limbs.ts      the ten independent voters, each -1 … +1 with a reason string
  frankenstein.ts  the blend + the regime gate
  autotrader.ts    paper execution: resting Goldbach limits (or next-bar-open
                   fills), stop-before-target within a bar, scale-outs,
                   trailing, equity + stats
```

Entry style is switchable in the panel. On the synthetic demo feed, across six
symbols and 500 1h bars, resting limits beat market entries (−14.7R vs −42.1R,
with 135 of 151 entries filling on a level) — both negative, which is what a
random walk should do to any system.

Nothing in `src/model` touches the DOM, so the bot in `bot/` can import the same
ensemble the chart runs. Turn it on with the **🧠 AI Trader** button in the
toolbar (or the `Frankenstein AI` / `Frankenstein Score` indicators); the
right-hand panel shows the current limb-by-limb breakdown, the open paper
position and the run's statistics.

> The trader simulates its own fills against the candles it is handed. It places
> no orders anywhere, and back-tested numbers on any feed — least of all the
> synthetic demo feed — are not a forecast.

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
  model/       Frankenstein ensemble: features, limbs, blend, paper trader
  ui/          React shell: toolbar, layouts, watchlist, search
```

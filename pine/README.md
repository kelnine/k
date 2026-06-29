# Pine Scripts

TradingView indicators that mirror the native KCharts overlays, for use directly
on TradingView charts (NQ/ES futures, crypto, anything with volume).

## DepthFlow.pine

A clean-room order-flow / liquidity overlay — the same feature set as the
`DepthFlow` overlay in this app (`src/indicators/depthflow.ts`):

- **Volume blocks** — volume-by-price profile; high-volume nodes drawn as
  horizontal liquidity bands (red supply above price, green demand below),
  labelled with traded volume and the buy/sell split.
- **Spot dominance** — buy vs. sell volume (close-location method) over a recent
  window, shown top-right as `B xx%  S yy%`.
- **Sweeps** — wicks that pierce a recent swing high/low and close back inside.
- **Displacement** — impulsive candles whose body exceeds an ATR multiple.

### Install

1. Open TradingView → **Pine Editor** (bottom panel).
2. Paste the contents of `DepthFlow.pine`.
3. Click **Add to chart**.
4. Tune inputs (lookback, bins, node threshold, dominance window, swing
   strength, ATR multiple) from the indicator's settings gear.

Everything is computed from raw OHLCV — no external data feed required. Note
the buy/sell split is *inferred* from each candle's close location, the same
approximation retail "order-flow on TradingView" tools use; it is not true
bid/ask tape, which TradingView does not expose to Pine.

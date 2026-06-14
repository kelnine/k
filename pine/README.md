# Phantom Flow [KN] — Pine v6 indicator

An all-in-one Smart Money Concepts overlay for TradingView, built from scratch
(no `request.security()`, ASCII-only source to avoid curly-quote paste errors).

## Load it

1. Open TradingView → **Pine Editor**.
2. Paste the contents of [`PhantomFlow.pine`](./PhantomFlow.pine).
3. **Save**, then **Add to chart**. Works on any symbol / timeframe.

## What's in v1

| Feature | How it works |
| --- | --- |
| **Trend cloud** | Fast/slow EMA cross with an ATR band — one clean up/down read. |
| **Buy / Sell zones** | Demand band around the latest swing low, supply band around the latest swing high (ATR-padded). |
| **BOS / CHoCH** | Labels on structure breaks; CHoCH when the break flips the prior bias, BOS when it continues it. |
| **Order blocks** | Anchored to the last opposite candle before a break. Capped to `Max Order Blocks`, auto-removed once mitigated. |
| **Fair value gaps** | 3-candle gap boxes, capped, removed once filled. |
| **Signals** | Buy/sell triangles gated on trend + zone touch + confluence, with min-bar spacing so they don't cluster. |
| **Dashboard** | Top-right table: Trend, Structure, Signal, Confluence X/5. |
| **Alerts** | Buy, Sell, Bullish break, Bearish break. |

## Tuning levers (inputs)

- **Confluence** — `Min Confluence To Signal` (1–5) raises/lowers how strict a
  signal is. Score = trend + structure bias + zone touch + EMA momentum + break.
- **Signals** — `Min Bars Between Signals` controls clustering.
- **Order Blocks** — `OB Search Lookback`, `Max Order Blocks`, mitigation on/off.
- **Trend** — EMA lengths, ATR length, cloud width.

## Next steps (roadmap)

- Gate signals harder on confluence once we see live behavior.
- OB refinement (inner/outer two-layer rendering like the reference product).
- Fold the older FutureFi Core / AlgoAlpha scripts up to this standard.
- Landing site (single self-hosted HTML page).

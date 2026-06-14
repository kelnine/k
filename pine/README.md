# FutureFi — Pine v6 indicator

An all-in-one Smart Money Concepts overlay for TradingView, built from scratch
(no `request.security()`, ASCII-only source to avoid curly-quote paste errors).

## Load it

1. Open TradingView → **Pine Editor**.
2. Paste the contents of [`FutureFi.pine`](./FutureFi.pine).
3. **Save**, then **Add to chart**. Works on any symbol / timeframe.

## What's inside

| Feature | How it works |
| --- | --- |
| **Trend cloud** | Fast/slow EMA cross with an ATR band — one clean up/down read. |
| **Premium / discount / EQ** | 50% equilibrium of the latest swing range; flags whether price is at a discount (buy side) or premium (sell side). |
| **Buy / Sell zones** | Demand band around the latest swing low, supply band around the latest swing high (ATR-padded). |
| **BOS / CHoCH** | Labels on structure breaks; CHoCH when the break flips the prior bias, BOS when it continues it. |
| **Liquidity sweeps** | Marks stop-hunts — a wick beyond a swing that closes back inside. |
| **Order blocks** | Two-layer: faint outer wick band + solid inner body, anchored to the last opposite candle before a break. Capped and auto-removed once mitigated. |
| **Fair value gaps** | 3-candle gap boxes, capped, removed once filled. |
| **Signals** | Buy/sell triangles gated on trend + location + momentum + confluence, with min-bar spacing. |
| **Trade levels** | Auto entry / stop / target lines + labels on the latest signal, sized to your Risk:Reward. |
| **Dashboard** | Top-right: Trend, Structure, Momentum (RSI), Volume, Bias, Signal, Confluence X/6. |
| **Alerts** | Buy, Sell, Bullish/Bearish break, Bullish/Bearish sweep. |

## Confluence score (out of 6)

For a long, each adds a point: trend up · bullish structure · price at
discount/buy-zone · momentum (RSI ≥ 50) · high volume · break-or-sweep. Shorts
mirror it. `Min Confluence To Signal` sets the bar a signal must clear.

## Tuning levers (inputs)

- **Signals** — `Min Confluence To Signal` (1–6), `Min Bars Between Signals`,
  toggle the momentum and volume requirements.
- **Trade Levels** — `Risk : Reward`, level length, show/hide.
- **Order Blocks** — search lookback, max count, mitigation on/off.
- **Trend** — EMA lengths, ATR length, cloud width.

## Roadmap

- Fold the older FutureFi Core / AlgoAlpha scripts up to this standard.
- Landing site (single self-hosted HTML page).

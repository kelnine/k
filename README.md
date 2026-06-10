# Volume Profile Pro — Indicator + Strategy (TradingView / Pine Script v6)

Two scripts built around a rolling **volume profile** — the map of *where* volume
traded, not just *when*:

| File | Type | What it does |
|---|---|---|
| `volume_profile_indicator.pine` | Indicator (overlay) | Draws the profile, key levels, and a forecast panel with a projected price target |
| `volume_profile_strategy.pine` | Strategy (backtestable) | Trades value-area reversion and breakouts off the same profile engine |

## Installation

1. Open any chart on [TradingView](https://tradingview.com) → **Pine Editor** (bottom panel).
2. Paste the contents of either file → **Add to chart**.
3. For the strategy, open **Strategy Tester** to see backtest results.

Works on any symbol/timeframe that has volume data (stocks, futures, crypto).
Forex spot volume is tick volume — treat results there with extra skepticism.

## How the engine works

Over the last *N* bars (default 200 for the indicator, 150 for the strategy),
each bar's volume is distributed across the price rows its high–low range
touches. From that histogram we derive:

- **POC (Point of Control)** — the single price with the most traded volume.
  The market's strongest "magnet"; price tends to rotate back to it.
- **VAH / VAL (Value Area High/Low)** — the band holding 70% of volume
  (expanded outward from the POC). Inside = acceptance, outside = imbalance.
- **HVN / LVN** — high-volume nodes act as support/resistance shelves;
  low-volume nodes are vacuums price tends to slice through quickly.
- **Delta profile** (indicator only) — each row colored by whether up-bar or
  down-bar volume dominated, approximating buyer vs. seller initiative.

## The "prediction" — what it actually is

The indicator's forecast panel scores four conditions into a bias from −4 to +4:

1. Close above/below the POC (which side of acceptance price trades on)
2. Net buy/sell delta across the whole profile
3. Acceptance outside the value area (close beyond VAH/VAL)
4. Trend agreement (21 EMA vs. 50 EMA)

A bias of ±2 or stronger projects a target: the **next HVN in that direction**
(the next magnet), or a **one-value-area-width extension** if price has already
broken out of value. Neutral bias projects rotation back to the **POC**.

This is a probabilistic auction-theory read, not fortune telling. No indicator
predicts price; this one tells you where the highest-odds destinations sit and
which one current order flow favors. Trade it with stops.

## Strategy playbooks

| Regime (ADX-based in Adaptive mode) | Entry | Target | Stop |
|---|---|---|---|
| Ranging — **Mean Reversion** | Price re-enters value through VAL (long) / rejected at VAH (short) | POC | ATR × 2 |
| Trending — **Breakout** | Volume-confirmed close beyond VAH/VAL | One value-area-width extension | ATR × 2 |

Extra protection: optional 200-EMA trend filter, time stop (default 40 bars),
date-range filter, and realistic costs baked in (0.05% commission + 2 ticks
slippage). Position size defaults to 10% of equity per trade.

## Tuning tips

- **Lookback** ≈ the auction you care about: ~150–200 bars on intraday charts
  approximates 1–2 sessions; on dailies it's a multi-month composite.
- **Rows**: more rows = finer levels but noisier nodes. 30–40 is a good balance.
- Lower `Volume spike multiple` (e.g. 1.2) on quiet symbols if breakout
  signals never fire; raise it on noisy crypto pairs.
- Backtest across several symbols and date windows before trusting any
  parameter set — profile strategies are regime-sensitive by nature.

## Disclaimer

Educational software, not financial advice. Past backtest performance does not
guarantee future results. Risk only what you can afford to lose.

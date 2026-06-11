# Volume Profile Pro v2 — Indicator + Strategy (TradingView / Pine Script v6)

Two scripts built around a rolling **volume profile** — the map of *where* volume
traded, not just *when*:

| File | Type | What it does |
|---|---|---|
| `volume_profile_indicator.pine` | Indicator (overlay) | Draws the profile, key levels, dashboard, and a projected price target |
| `volume_profile_strategy.pine` | Strategy (backtestable) | Trades value-area reversion and acceptance-confirmed breakouts off the same profile engine |

## Installation

1. Open any chart on [TradingView](https://tradingview.com) → **Pine Editor** (bottom panel).
2. Paste the contents of either file → **Add to chart**.
3. For the strategy, open **Strategy Tester** to see backtest results.

Works on any symbol/timeframe that has volume data (stocks, futures, crypto).
Forex spot volume is tick volume — treat results there with extra skepticism.

## How the engine works

Over a lookback window (**auto-tuned per timeframe** by default — ≤15m → 300
bars, 1H–3H → 240, 4H → 180, daily → 110, weekly → 60), each bar's volume is
distributed across the price rows its high–low range touches. From that
histogram we derive:

- **POC (Point of Control)** — the single price with the most traded volume.
  The market's strongest "magnet"; price tends to rotate back to it.
- **VAH / VAL (Value Area High/Low)** — the band holding 70% of volume
  (expanded outward from the POC). Inside = acceptance, outside = imbalance.
- **HVN / LVN** — high-volume nodes act as support/resistance shelves;
  low-volume nodes are vacuums price tends to slice through quickly.
- **True intrabar delta** (indicator) — buy/sell volume summed from
  lower-timeframe bars (1m–60m depending on chart TF), so row coloring and
  the net-delta reading reflect real order flow, not just candle color.
  Falls back to candle direction where intrabar history runs out.

## The "prediction" — what it actually is

The indicator scores five conditions into a bias from −5 to +5:

1. Close above/below the POC (which side of acceptance price trades on)
2. Net buy/sell delta across the whole profile
3. **Acceptance** — two or more consecutive closes held outside the value area
4. Trend agreement (21 EMA vs. 50 EMA)
5. Recent delta momentum (14-EMA of per-bar delta)

A bias of ±2 or stronger projects a target — the **next HVN in that direction**
(the next magnet), or a **one-value-area-width extension** if price has already
broken out of value — and draws an arrow to it on the chart. Neutral bias
projects rotation back to the **POC**. The dashboard (top right) shows the
bias, conviction, target with distance, levels, net delta, and the current
ADX regime at a glance.

This is a probabilistic auction-theory read, not fortune telling. No indicator
predicts price; this one tells you where the highest-odds destinations sit and
which one current order flow favors. Trade it with stops.

## Strategy playbooks

| Regime (ADX-based in Adaptive mode) | Entry | Target | Initial stop |
|---|---|---|---|
| Ranging — **Mean Reversion** | Price re-enters value through VAL (long) / rejected at VAH (short) | POC | ATR × 2 |
| Trending — **Breakout** | N consecutive closes accepted beyond VAH/VAL (default 2) + volume spike in that window | One value-area-width extension | ATR × 2 |

**Risk engine:**
- Position is sized so each trade risks a **fixed % of equity** (default 1%),
  derived from the stop distance, capped at 100% of equity notional.
- Optional scale-out (on by default): **bank 50% at 1R**, move the stop to
  **breakeven**, then **ATR-trail** the runner toward the profile target.
- Time stop (default 40 bars), EMA-200 trend filter, date-range filter, and
  realistic costs baked in (0.05% commission + 2 ticks slippage).

## Tuning tips

- **Lookback Auto** matches the auction to the timeframe; switch to Manual if
  you want a specific composite (e.g. 90 on daily for a tighter value area).
- **Rows**: more rows = finer levels but noisier nodes. 30–40 is a good balance.
- **Breakout acceptance**: 1 = enter on the cross (fast, more fakeouts),
  2–3 = wait for confirmed acceptance outside value (fewer, better trades).
- Lower `Volume spike multiple` (e.g. 1.2) on quiet symbols if breakout
  signals never fire; raise it on noisy crypto pairs.
- Backtest across several symbols and date windows before trusting any
  parameter set — profile strategies are regime-sensitive by nature.

## Disclaimer

Educational software, not financial advice. Past backtest performance does not
guarantee future results. Risk only what you can afford to lose.

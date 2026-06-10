# Apex Scalper v6 — 1-Minute Trend-Pullback System

A Pine Script **v6** trading system for TradingView, purpose-built for **1-minute
charts**. It ships as two files:

| File | Type | Use it for |
|---|---|---|
| `apex_scalper_strategy.pine` | `strategy()` | Backtesting, optimization, automated order simulation |
| `apex_scalper_indicator.pine` | `indicator()` | Real-time alerts (manual trading or webhook automation) |

Both share identical signal logic, so what you backtest is what you alert on.

## How it works

The system only trades **with** the higher-timeframe trend and enters on
**momentum resumption after a shallow pullback** — the structure that gives
1-minute systems consistency, because it avoids the choppy, mean-reverting
conditions that destroy most scalpers.

A signal requires **all** of the following confluences:

1. **HTF bias** — price above/below a 50 EMA on the 5-minute chart (non-repainting: uses the last *confirmed* HTF value).
2. **EMA stack** — 21 EMA above/below 50 EMA on the 1-min chart.
3. **VWAP side** — price on the correct side of session VWAP (toggleable).
4. **Trend strength** — ADX above 18, filtering out chop.
5. **Pullback** — price touched the 21 EMA within the last 8 bars.
6. **Trigger** — a momentum candle closing back through the EMA *and* through the prior bar's high/low.
7. **RSI window** — RSI confirms direction (>50 for longs) but blocks exhaustion entries (<70).
8. **Volume spike** — current volume > 1.2× its 20-bar average.

### Risk engine (strategy)

- **Stop loss:** 1.2 × ATR(14) from entry.
- **Take profit:** 1.8R (i.e., 1.8× the stop distance) — positive expectancy at ~40%+ win rate before costs.
- **Break-even:** stop moves to entry once the trade reaches +1R (toggleable).
- **Optional ATR trailing stop** (2 × ATR) that replaces the fixed TP to ride runners.
- **Guards:** session filter (default 09:30–15:30 New York), max 10 trades/day, 5-bar cooldown after a loss, 3% daily loss cap, forced flat at session end.
- **Realistic costs baked in:** 0.02% commission + 1 tick slippage per fill. Keep these on — a 1-min backtest without costs is fiction.

## Setup

1. In TradingView open **Pine Editor**, paste `apex_scalper_strategy.pine`, click **Add to chart**.
2. Set the chart to **1 minute** on a liquid instrument (MES/MNQ/ES/NQ futures, EURUSD/GBPUSD, BTC/ETH perps, or high-volume large caps).
3. Open the **Strategy Tester** tab and review Net profit, Profit factor, Max drawdown, and trade count (you want 100+ trades for the stats to mean anything).
4. For live alerts, add `apex_scalper_indicator.pine` to the chart and create alerts on **"Any alert() function call"** (messages include entry/SL/TP) or on the named *Apex Long / Apex Short* conditions.

## Tuning per instrument

These defaults are a sane starting point, not magic numbers. Tune in this order:

| Symptom | Adjust |
|---|---|
| Too few trades | Lower `Min ADX` (18 → 14), lower `Volume spike` (1.2 → 1.0), widen `Pullback window` |
| Chopped up by noise | Raise `Min ADX` (18 → 22–25), raise `Volume spike` (1.2 → 1.5) |
| Stopped out then move goes your way | Raise `Stop loss × ATR` (1.2 → 1.5–2.0) and re-tune the R multiple |
| Winners reverse before target | Lower the `R multiple` (1.8 → 1.3–1.5) or enable break-even earlier |
| Strong trending instrument (NQ, BTC) | Enable the **ATR trailing stop** instead of fixed TP |
| Crypto / 24h markets | Disable the session filter or set it to the high-volume window |

After tuning, **walk-forward test**: optimize on one date range, then verify on
unseen later data. If performance collapses out-of-sample, you've overfit —
loosen the parameters back toward defaults.

## Honest disclaimer

No script can guarantee profits, and anyone claiming a "high-profit" 1-minute
strategy without caveats is selling something. This system is built on sound
principles — trade with the trend, cut losses at a fixed R, let winners run
further than losers, cap daily damage — which is what produces *consistency*.
Expected behavior when well-tuned is roughly a 40–55% win rate with average
winners larger than average losers. Backtest thoroughly, paper trade before
risking capital, and never risk more per trade than you can lose ten times in
a row. Past performance does not predict future results. This is not financial
advice.

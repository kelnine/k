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

9. **Overextension guard** — the trigger bar's range must be ≤ 1.5× ATR and price ≤ 1× ATR from the fast EMA, so the system never chases climax candles.
10. **Slope filter** — the slow EMA must actually be rising (longs) / falling (shorts), not flat.

### Risk engine (strategy)

- **Stop loss:** 1.5 × ATR(14) from entry — wide enough to survive 1-min noise.
- **Scale-out exits:** 50% of the position takes profit at **TP1 (1R)**; the stop on the remainder moves to break-even; the runner targets **TP2 (2.2R)**. This is what produces *consistency*: many trades bank the partial and scratch the rest, while runners pay for the losers.
- **Optional ATR trailing stop** (2 × ATR) on the runner instead of a fixed TP2.
- **Guards:** optional session filter (off by default — enable 09:30–15:30 NY for stocks/index futures), max 15 trades/day, 3-bar cooldown after a loss, 3% daily loss cap, forced flat at session end when the filter is on.
- **Realistic costs baked in:** 0.02% commission + 1 tick slippage per fill. Keep these on — a 1-min backtest without costs is fiction.

### Visuals

Gradient **trend cloud** between the EMAs, compact ▲/▼ signal markers with the
full trade plan (entry/SL/TP1/TP2) in a **hover tooltip**, shaded **risk/reward
zone boxes** on each signal, optional trend-colored bars, a live **dashboard**
(bias, ADX, RSI, volume, VWAP side, session), and the strategy's performance
table. Everything is toggleable in the *Display* input group.

## Setup

1. In TradingView open **Pine Editor**, paste `apex_scalper_strategy.pine`, click **Add to chart**.
2. Set the chart to **1 minute** on a liquid instrument (MES/MNQ/ES/NQ futures, EURUSD/GBPUSD, BTC/ETH perps, or high-volume large caps).
3. Open the **Strategy Tester** tab and review Net profit, Profit factor, Max drawdown, and trade count (you want 100+ trades for the stats to mean anything).
4. For live alerts, add `apex_scalper_indicator.pine` to the chart and create alerts on **"Any alert() function call"** (messages include entry/SL/TP) or on the named *Apex Long / Apex Short* conditions.

## Tuning per instrument

These defaults are a sane starting point, not magic numbers. Tune in this order:

| Symptom | Adjust |
|---|---|
| Too few trades | Lower `Min ADX` (15 → 12), turn off the `RSI momentum filter` and/or `Require volume above average` toggles, widen `Pullback window`, raise the stretch/bar-range caps |
| Chopped up by noise | Raise `Min ADX` (15 → 20–25), raise `Volume ×` (1.0 → 1.3–1.5), enable `Trigger must break prior bar high/low` |
| Stopped out then move goes your way | Raise `Stop loss × ATR` (1.2 → 1.5–2.0) and re-tune the R multiple |
| Winners reverse before target | Lower the `R multiple` (1.8 → 1.3–1.5) or enable break-even earlier |
| Strong trending instrument (NQ, BTC) | Enable the **ATR trailing stop** instead of fixed TP2 |
| Crypto / 24h markets | Disable the session filter or set it to the high-volume window |

### Crypto perpetuals (BTC/ETH) starting point

- **Session filter:** either disable it, or restrict to the US/EU overlap
  (`1300-2100` UTC) where BTC actually trends on the 1-min.
- **Commission:** set it to your real taker fee (often 0.04–0.06% on perps —
  *higher* than the 0.02% default; this alone can flip a marginal backtest).
- **Filters:** ADX 22–25 and volume spike 1.3–1.5 — BTC 1-min has more noise
  than index futures, so demand stronger confirmation and accept fewer trades.
- **Exits:** enable the ATR trailing stop on the runner; BTC trends pay best
  when you let the second half ride.

### If your backtest is negative

1. Check **trade count** — under ~100 trades the result is noise either way.
2. Check **avg win vs avg loss** — if winners are smaller than losers, widen
   the stop (1.5 → 2.0 ATR) or raise TP2.
3. Check **win rate** — below ~35% means the filters aren't selective enough
   for that instrument: raise ADX and the volume multiplier.
4. Make sure commission/slippage match your real broker — then *never* tune
   them down to make results look better.
5. Try the trailing-stop runner; on trending instruments fixed targets often
   leave the profit on the table.

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

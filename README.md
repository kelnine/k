# Rebellio Market — Automated TradingView Strategy

A Pine Script v5 strategy that automates the trading system taught across
[@RebellioMarket](https://x.com/RebellioMarket)'s X posts, so you can **see
every signal on your chart, backtest it, and wire it to a broker** for true
automation.

## What it does

| Mode | Timeframe | Logic |
|------|-----------|-------|
| **Day Trade (VWAP)** | 1m–5m | Break/hold above VWAP + EMA9>EMA20 + volume expansion |
| **Swing (4H EMA+RSI)** | 4H | Price > 200 EMA, pullback to 20 EMA, rejection candle, RSI > 50 |

**Shared risk engine** (from their `$1K Day Trading Plan` post):
- 2% risk per trade (auto position sizing)
- 1:2 minimum reward-to-risk targets
- Max 3 trades/day + 4% daily loss cutoff (day mode)
- Auto stop-loss (below VWAP / pullback low) and take-profit

## Quick start (see it on TradingView)

1. Open TradingView → **Pine Editor** (bottom panel).
2. Paste the contents of [`rebellio_market_strategy.pine`](./rebellio_market_strategy.pine).
3. Click **Add to chart**.
4. Pick your mode in the settings gear:
   - **Day Trade** → use a 1m or 5m chart.
   - **Swing** → use a 4H chart.
5. Open the **Strategy Tester** tab to backtest. On-chart labels show every
   entry, stop (SL) and target (TP). The top-right table shows live stats.

## True automation (auto-execute trades)

Pine Script can't place trades by itself — it fires **alerts**. To auto-execute:

1. Click the **Alert** (clock) icon → Condition = *Rebellio Market — Auto Strategy*.
2. Set **"alert() function calls only"**.
3. Paste your broker/connector **webhook URL** (e.g. a TradingView→broker bridge).
4. The alert ships ready-to-parse JSON:
   ```json
   {"action":"buy","symbol":"AAPL","qty":12.5,"stop":187.20,"target":195.60}
   ```

## ⚠️ Disclaimer

Educational tool only. No strategy is guaranteed profitable. Backtest results
do not predict future returns. Trade with capital you can afford to lose.

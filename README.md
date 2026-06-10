# BOS + Trend — Multi-Timeframe Strategy (Pine Script v6)

A fully backtestable TradingView **strategy** (`strategy()`, not an indicator)
that trades a Break-of-Structure + trend-following model across three timeframes:

| Step | TF | Job | How it's coded |
|------|----|-----|----------------|
| **1. Bias**         | 1H  | Direction | Price above **EMA 50 & EMA 200** = bullish; below both = bearish. Optional clean EMA stack. |
| **2. Confirmation** | 15M | Setup | Trend holds the EMAs **and** a **pullback** into the fast-EMA zone occurred. |
| **3. Entry**        | 5M  | Trigger | A **Break of Structure (BOS)** in the trend direction, then a **retest** of the broken level. |

Open the chart on your **5M entry timeframe** — the 1H bias and 15M confirmation
are pulled automatically.

> ⚠️ Educational backtesting tool, not financial advice. Forward-test on a demo
> account before risking real capital.

## Account-size neutral

No fixed account size or money amounts. Position size is computed from a
**risk-per-trade %** input and the stop distance:

```
quantity = (equity × risk%) ÷ stop distance
```

Change `initial_capital` in the Strategy properties to anything you like — the
risk model scales automatically.

## Trade rules

- **Long** after bullish BOS + pullback/retest + 1H bias confirmed.
- **Short** after bearish BOS + pullback/retest + 1H bias confirmed.
- **No counter-trend trades** — opposite breaks cancel a pending setup; one
  position at a time (`pyramiding = 0`).
- **Failed-break invalidation** — a pending setup is dropped if price closes
  decisively back through the broken level before the retest.
- **Anti-overtrading:** optional **cooldown** between trades and optional
  **max trades per day**. Setups also **expire** if the retest never comes.

## Quality filters (all optional, on by default)

- **HTF EMA-slope** — longs only when the 1H fast EMA is rising, shorts only
  when it is falling.
- **ADX trend strength** — skip trades when ADX is below a threshold (avoids chop).
- **BOS momentum** — the breakout must clear the swing by a minimum ATR fraction,
  filtering weak/marginal breaks.
- **Entry-confirmation candle** — the retest bar must close in the trade direction.

## Equity guards (account-neutral)

- **Daily-loss lockout** — stop new entries once the day is down X% of equity.
- **Max-drawdown lockout** — halt entries if equity falls X% below its peak.

## Risk management

- Stop loss from **recent swing** *or* **ATR** (selectable), with a buffer.
- **TP1 at 1R, TP2 at 2R, optional runner at 3R** (all R-multiples adjustable).
- Scale-out percentages per target.
- **Break-even** move after TP1 (toggle).
- **ATR trailing stop** (toggle).

## Visuals (all toggleable)

- EMA 50 & EMA 200.
- BOS labels (▲ / ▼).
- Entry labels (LONG / SHORT).
- SL / TP1 / TP2 / TP3 lines.
- 1H bias background tint.

## Backtest dashboard

Top-right panel: total trades, win rate, profit factor, payoff ratio (avg
win / avg loss), net profit, net %, max drawdown, average trade, open P/L,
live ADX, current bias (Bullish / Bearish / Neutral) and the trading status
(Active / Day Lock / DD Lock / Max Trades).

## No repainting / no lookahead

- Higher/lower-timeframe data is read through a **confirmed-bar wrapper** with
  `lookahead = barmerge.lookahead_off`.
- BOS uses **confirmed swing pivots**; orders process on bar close.

## Install

1. TradingView → **Pine Editor** → paste [`FutureFi_BOS_Trend.pine`](./FutureFi_BOS_Trend.pine).
2. **Add to chart**, set the chart to **5M**.
3. Open **Strategy Tester** to read the stats; tune inputs and re-run.

### Tuning: win rate vs profit target

- More winners → lower `TP1 (R)` toward ~1.0 and keep break-even on.
- Bigger targets → raise the runner `TP3 (R)` to 3R+ and shrink `TP1 size (%)`.
- Fewer/cleaner trades → raise `Swing pivot lookback`, keep EMA stack + pullback on.

Let the Strategy Tester numbers decide after each change.

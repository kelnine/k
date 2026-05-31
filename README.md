# FutureFi — BOS + Trend Funded Account Framework (Pine Script v6)

A backtestable TradingView strategy that codifies the **FutureFi "BOS + Trend"**
discretionary playbook (concept by [@Kelnine0](https://twitter.com/Kelnine0))
into mechanical, multi-timeframe rules.

Tuned with a **balanced profile**: a partial take-profit at **1.5R**, a **2.5R
runner**, and an automatic move to **break-even** after the first target — built
to keep a healthy win rate while still reaching for a strong reward:risk.

> ⚠️ Educational backtesting tool, not financial advice. Past performance does
> not guarantee future results. Forward-test on a demo account first.

---

## The three steps (exactly as in the framework)

| Step | Timeframe | Job | How it's coded |
|------|-----------|-----|----------------|
| **1. Bias**         | 1H  | Direction | Price above/below **50 & 200 EMA** (optional clean EMA stack). Bull or Bear only. |
| **2. Confirmation** | 15M | Setup | Trend holds the EMAs **and** a **pullback** into the 50-EMA zone occurred. |
| **3. Entry**        | 5M  | Trigger | A **Break of Structure (BOS)** in the trend direction, then a **retest** of the broken level. |

You only ever open the chart on the **5M entry timeframe** — the 1H bias and 15M
confirmation are pulled automatically with `request.security`.

## The Golden Rule (risk) — all enforced in code

- **Risk per trade:** fixed dollar risk ($25–$40 on a $5k account). Position
  size is computed from the stop distance, so every trade risks the same amount.
- **Max 2 trades per day** (configurable).
- **Daily loss lockout** — stops trading for the day once the daily loss limit hits.
- **Account drawdown lockout** — protects starting capital; stops entirely if
  equity falls too far below the account size.
- **NEVER trade 1-minute** — sub-5-minute timeframes are blocked.

## "Do not trade if…" — handled automatically

- **No 1H bias** → no setup is armed.
- **Counter-trend BOS** → ignored; an opposite break while waiting cancels the setup.
- **Entering without a retest** → entries only fire on the retest trigger.
- **Reverse trading** → `pyramiding = 0`, one position at a time.

---

## Install

1. Open **TradingView → Pine Editor**.
2. Paste the contents of [`FutureFi_BOS_Trend.pine`](./FutureFi_BOS_Trend.pine).
3. Click **Add to chart**.
4. Set the chart to your **5M entry timeframe**.
5. Open the **Strategy Tester** tab to read Net Profit, **Win Rate**, Profit
   Factor and the trade list.

## On-chart dashboard

A panel (top-right) shows live 1H bias, 15M setup state, whether a retest is
pending, trades used today, day P/L, and the trading/lockout status.

## Key settings to tune

| Setting | Default | Effect |
|---------|---------|--------|
| `TP1 reward:risk` | 1.5 | Lower → more winners, smaller gains. Higher → bigger but rarer. |
| `TP2 reward:risk (runner)` | 2.5 | The runner target. |
| `TP1 size (%)` | 50 | How much is banked at TP1 vs left to run. |
| `Move stop to break-even after TP1` | on | Cuts give-back on runners (boosts win rate). |
| `Swing pivot lookback` | 5 | Higher = stronger, fewer BOS signals. |
| `Retest tolerance (× ATR)` | 0.5 | How close price must return to the broken level. |
| `Require clean EMA stack` | on | Filters chop; turn off for more trades. |
| `Require a pullback` | on | Core to the framework; off = more (lower-quality) entries. |

> **Win rate vs profit target:** to push the win rate higher, drop `TP1 reward:risk`
> toward 1.0 and keep break-even on. To chase bigger targets, raise the runner to
> 3R+ and reduce the TP1 size. Re-run the Strategy Tester after each change and
> let the numbers decide.

## Important notes

- Built for assets where TradingView provides aligned 1H/15M/5M data (forex,
  crypto, indices/futures).
- BOS uses confirmed swing pivots, so the entry timeframe does **not** repaint;
  always confirm results in the Strategy Tester before going live.

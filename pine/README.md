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

#### Alerts

The indicator emits `alertcondition`s you can wire up via TradingView's **Add
alert** dialog (pick "DepthFlow" as the condition):

- *Sweep (sell-side / buy-side)* — a raw liquidity grab fired.
- *Displacement up / down* — an impulsive candle fired.
- *LONG setup* — sweep + displacement up **at a demand block** (the high-
  confluence long).
- *SHORT setup* — sweep + displacement down **at a supply block**.

`LONG`/`SHORT` labels also print on the chart at those confluence points.

## DepthFlowStrategy.pine

A `strategy()` backtest of the DepthFlow playbook so you can measure whether the
setup actually has an edge on **your** symbol/timeframe — load it and open the
**Strategy Tester** tab for win rate, profit factor, and max drawdown.

Rule: a liquidity sweep arms a setup; a same-direction displacement candle
within `confirmBars` confirms it; entry at that close, stop just beyond the
sweep extreme, target an R-multiple of the risk. Position size comes from a
fixed **% account risk per trade** (default 1%). Inputs cover swing strength,
ATR/displacement, R-multiple, stop buffer, an optional session filter, and
long/short toggles. Commission + slippage are on by default — keep them
realistic so the results aren't fantasy.

> Educational backtesting only, not financial advice. Past performance does not
> predict future results.

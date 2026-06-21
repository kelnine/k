# Jetstream — Pine Script v6

Free, from-scratch TradingView indicators that replicate the look of premium
"buy/sell signal + money-flow wave" packs. No licensed or lifted code — they're
built from public techniques (ATR SuperTrend + WaveTrend), so they're fully
auditable and cost nothing.

Because TradingView gives each `indicator()` a single `overlay` setting, the
on-chart pieces and the oscillator pane normally have to be separate scripts.
Pine v6's `force_overlay = true` gets around that, so there are two ways to run
Jetstream:

| File | Add to chart | Result |
| --- | --- | --- |
| `jetstream.pine` | once | **All-in-one.** Waves in a sub-pane; trail, ribbon and signals forced onto the price chart. Recommended. |
| `jetstream_strategy.pine` | once | **Backtestable.** Same visuals, but the trend flips drive stop-and-reverse orders so it runs in the Strategy Tester. |
| `jetstream_trend.pine` | on the price chart | Just the trail + ribbon + BUY/SELL labels (modular). |
| `jetstream_waves.pine` | its own sub-pane | Just the WaveTrend rainbow waves + money-flow area (modular). |

Use **`jetstream.pine`** for charting, or **`jetstream_strategy.pine`** to
backtest. The two modular files are kept for anyone who wants only one half.

## Backtesting (`jetstream_strategy.pine`)

Add it to the chart, then open the **Strategy Tester** tab at the bottom for the
performance summary, equity curve and trade list. Entries are stop-and-reverse
on the trend flips. Useful knobs under *Strategy*:

- **Direction** — Both / Long only / Short only.
- **Require wave agreement** — only take a flip when the WaveTrend confirms it
  (fewer, higher-quality trades).
- **Use ATR stop / target** — optional exits at `× ATR` from entry.
- **Limit date range** — backtest a specific window.

Defaults: 10k starting capital, 10% equity per trade, 0.05% commission, orders
filled on bar close. Tune these in the script's *Properties* tab. Past
performance is hypothetical and not a guarantee of future results.

## Install

1. Open TradingView → bottom panel → **Pine Editor**.
2. Paste the contents of `jetstream.pine`, click **Add to chart**. Done.
3. (Optional) Save it as a personal indicator so it's in your favourites.

## Alerts

Both scripts expose `alertcondition`s, so you can right-click → **Add alert**
and pick *Jetstream Buy/Sell* or *Jetstream Wave Buy/Sell*.

## Settings worth tuning

- **Trend** — `ATR Multiplier` (higher = fewer, slower flips), `ATR Length`.
  `Signals → Style` switches between **Labels** (BUY/SELL) and minimal
  **Triangles**. A combined *Jetstream Signal* alert fires on either side.
- **Waves** — `Channel`/`Average` length set the wave speed; `Overbought` /
  `Oversold` set where cross signals are allowed to fire. The green/red
  **money-flow area** behind the waves is toggled under *Money Flow*
  (`MF Length` / `MF Scale` control its smoothness and height).

## Note

This is a faithful *functional* equivalent of that style of indicator, not a
byte-for-byte copy of any specific paid script — exact entries will differ.
It's decision support, not a guarantee; size your risk accordingly.

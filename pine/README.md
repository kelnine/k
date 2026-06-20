# Jetstream — Pine Script v6

Free, from-scratch TradingView indicators that replicate the look of premium
"buy/sell signal + money-flow wave" packs. No licensed or lifted code — they're
built from public techniques (ATR SuperTrend + WaveTrend), so they're fully
auditable and cost nothing.

Because TradingView can't mix on-chart overlays and a separate oscillator pane
in a single script, this ships as two scripts (the same way the paid packs do):

| File | Pane | What it draws |
| --- | --- | --- |
| `jetstream_trend.pine` | on the price chart | ATR SuperTrend trail, EMA ribbon, ▲ BUY / ▼ SELL labels on trend flips |
| `jetstream_waves.pine` | its own sub-pane | WaveTrend oscillator as nested rainbow waves + OB/OS guides |

## Install

1. Open TradingView → bottom panel → **Pine Editor**.
2. Paste the contents of `jetstream_trend.pine`, click **Add to chart**.
3. Open a new Pine Editor tab, paste `jetstream_waves.pine`, **Add to chart**.
4. (Optional) Save each as a personal indicator so they're in your favourites.

## Alerts

Both scripts expose `alertcondition`s, so you can right-click → **Add alert**
and pick *Jetstream Buy/Sell* or *Jetstream Wave Buy/Sell*.

## Settings worth tuning

- **Trend** — `ATR Multiplier` (higher = fewer, slower flips), `ATR Length`.
- **Waves** — `Channel`/`Average` length set the wave speed; `Overbought` /
  `Oversold` set where cross signals are allowed to fire.

## Note

This is a faithful *functional* equivalent of that style of indicator, not a
byte-for-byte copy of any specific paid script — exact entries will differ.
It's decision support, not a guarantee; size your risk accordingly.

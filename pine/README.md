# Pine Script

TradingView ports of the KCharts setup. Written for **Pine Script v6**.

## `kcharts-setup.pine`

One overlay covering the whole setup, so nothing else needs to be on the chart:

- **Pullback EMA band** — fast/slow EMAs (9 / 21 by default) shaded as a band that
  colours with trend. Optional triangles mark a pullback *tap*: a wick into the
  band with the trend that closes back out of it.
- **Anchored VWAP** — session / week / month / quarter / year anchor, with
  optional ±σ bands at two multipliers.
- **1H / 4H highs and lows** — previous-period high and low, the developing
  high and low of the period in progress, and an optional midpoint. Both
  timeframes are inputs, so the pair can be anything (15m/1H, 4H/1D, …).

### Installing

1. TradingView → **Pine Editor** → **Open** → *New indicator*.
2. Paste the contents of `kcharts-setup.pine`, replacing the template.
3. **Save**, then **Add to chart**.

### Notes

- Previous-period levels are read with `request.security(..., high[1], lookahead_on)`,
  which is the non-repainting form — the value only changes when a higher-timeframe
  bar closes.
- The *current* period high/low is a developing value by definition. It moves
  inside the bar; that is the point of it. Turn it off under **1H / 4H levels**
  if you only want settled levels.
- Levels are hidden when the chart timeframe is above the level's timeframe (a 1H
  level on a daily chart is just the previous bar).
- `Periods kept` controls how much history stays drawn. It defaults to `1` — only
  the live level — raise it to leave a trail of old highs and lows behind.

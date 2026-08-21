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
- **Key levels** — the standard reference set: previous day / week / month /
  quarter / year high, low and midpoint, the daily / weekly / monthly /
  quarterly / yearly opens, and the Monday high, low and mid. Each row has its
  own colour and its own high-low / mid / open toggles, so you can run just the
  handful you actually watch.

### Installing

1. TradingView → **Pine Editor** → **Open** → *New indicator*.
2. Paste the contents of `kcharts-setup.pine`, replacing the template.
3. **Save**, then **Add to chart**.

### Turning things off

Each block has a master switch at the top of its settings group — **Show EMA
band**, **Show VWAP**, **Show 1H / 4H levels**, **Show key levels** — so the
whole overlay can be pared back to one piece without touching the rest. Inside
the key-levels group each row also has its own high-low / mid / open toggles.

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
  the live level — raise it to leave a trail of old highs and lows behind. It
  applies to the 1H/4H levels; key levels always show the current one only.
- **Monday** means the week's first trading session, not the calendar day. On a
  holiday week that is Tuesday, and on futures it includes the Sunday-evening
  open — which is what you want, since that is the session the range belongs to.
  It is the one level tracked from chart bars rather than fetched, so it needs a
  real week rollover in the loaded history: on a 1m chart that starts mid-week,
  the Monday lines stay off until the following Sunday-evening open.
- Every key level hides itself when the chart timeframe is above its own, so a
  daily chart drops the previous-day lines instead of drawing the previous bar.
- Labels have two looks under **1H / 4H levels → Labels**: `Text` writes the name
  on the line, `Tag` puts it in a coloured bubble past the right edge.

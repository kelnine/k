# TradingView Pine Script (v6)

## `key-levels-rejection-zones.pine` — Key Levels • Zones • Structure [K]

An overlay that marks the levels and zones from the "mark your levels, wait for the
rejection" style of trading (built for XAUUSD on 1m–30m, works on any symbol), and
flags candles that reject them.

**Install:** TradingView → Pine Editor → paste the file → *Add to chart*.

### What it draws

| Group | Details |
|---|---|
| Key levels | Previous **and** current Month / Week / Day high-low, Friday close, daily/weekly open (off by default), round numbers, 4 manual levels (default names `WEEKLY RESISTANCE` / `WEEKLY SUPPORT` …). Labels that land on the same price merge into short names, e.g. `WH / DH / 30M R  74.30`, so they aren't cut off at the price scale. |
| HTF structure | Latest 4H and 30M swing **RESISTANCE / SUPPORT** + **4H SELL / BUY ZONES** (both timeframes configurable, non-repainting). |
| Sessions | Asia / London / New York high & low (dotted while the session is live, hidden once swept); session boxes optional (off by default). Default times are New York time: Asia 18:00–03:00, London 03:00–08:00, NY 08:00–17:00. |
| Structure | BOS / CHoCH. Every break of structure marks a **SELL / BUY ZONE** at the leg's origin candle; closed-through zones flip to **BREAKER**. A yellow **displacement** box covers the move from the zone to the break, only when that move was fast (≤ 20 bars), last 2 kept. |
| Imbalances | FVG → **IFVG** flip when price closes through. |
| Fibonacci | Auto fib on the latest structure leg at least 5 × ATR tall: 0 / 23.6 / 38.2 / 50 / 61.8 / 65 / 71 / 78.6 / 88.6 / 100 (editable) + OTE shading. 100% = origin of the leg, 0% = its extreme. Labels sit on the left so they don't collide with the key-level labels. |
| Volume profile | Lookback histogram split into buy (blue) / sell (red) volume, value area highlighted, POC level. Optional previous-day POC/VAH/VAL. |
| Extras | Optional swing rejection (wick) zones, EMAs 50/200. |

### Signals & alerts

A ▼ / ▲ label prints when a **closed** candle wicks through a level (or into a zone)
and closes back on the other side. The label names the level(s), e.g.
`▼ PDH + 4H SELL ZONE`. Signals only use closed candles, so they don't repaint.

Filters (all in *Rejection / Sweep Signals*):

- **Fresh level** (default 15 bars): the level/zone must have been untouched for the
  previous N bars, so you get the *first* test, not one signal per candle while price
  chops around it.
- **Min candle size** (0.5 × ATR) and **min wick** (35% of the candle).
- **Cooldown** (5 bars) between same-side signals.
- **Direction filter**: optionally only buy after a bullish BOS / sell after a bearish BOS.
- **Min confluence**: 2 = only candles that reject two or more things at once
  (e.g. `30M S + Ldn L + BUY ZONE`).
- **Signal hours**: any time, London + New York, or New York only.

*Signal Sources* picks which levels can fire: by default month/week/day levels,
Friday close, manual levels, HTF S/R, session highs/lows and sell/buy/HTF zones.
FVG/IFVG, round numbers, fib and volume-profile levels are drawn but don't fire
signals unless you switch them on, because they sit so close together that almost
every candle touches one.

Alerts: *Bearish / Bullish rejection / sweep*, *Bullish / Bearish BOS*, plus a dynamic
`alert()` message naming the level (create the alert with "Any alert() function call").

### Dashboard

Bias (price vs daily & weekly open), last BOS direction, active session, nearest
resistance/support with distance, day range vs ATR, and **signal stats**: every
signal is tracked with the stop just beyond the rejection wick and a target at a
fixed R multiple (default 1:2), shown as wins / losses / win rate / net R; a bar
that touches both counts as a loss. Break-even at 1:2 is a 33.3% win rate. It's a
quick, honest read of how the rejections on *your* symbol/timeframe actually
played out — check it before trusting any "90% win rate" claim.

### Notes

- Day/session levels need an intraday chart; weekly levels need ≤ daily.
- HTF inputs must be ≥ the chart timeframe (they're ignored otherwise).
- Everything is toggleable; if the chart feels busy, turn off session boxes,
  round numbers or the volume profile first.

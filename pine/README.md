# TradingView Pine Script (v6)

## `key-levels-rejection-zones.pine` — Key Levels • Zones • Structure [K]

An overlay that marks the levels and zones from the "mark your levels, wait for the
rejection" style of trading (built for XAUUSD on 1m–30m, works on any symbol), and
flags candles that reject them.

**Install:** TradingView → Pine Editor → paste the file → *Add to chart*.

### What it draws

| Group | Details |
|---|---|
| Key levels | Previous **and** current Month / Week / Day high-low, Friday close, daily/weekly open (off by default), round numbers, 4 manual levels (default names `WEEKLY RESISTANCE` / `WEEKLY SUPPORT` …). Labels that land on the same price merge, e.g. `MONTH HIGH / WEEK HIGH`. |
| HTF structure | Latest 4H and 30M swing **RESISTANCE / SUPPORT** + **4H SELL / BUY ZONES** (both timeframes configurable, non-repainting). |
| Sessions | Asia / London / New York high & low (dotted while the session is live, hidden once swept) + session boxes. Default times are New York time: Asia 18:00–03:00, London 03:00–08:00, NY 08:00–17:00. |
| Structure | BOS / CHoCH. Every break of structure marks a **SELL / BUY ZONE** at the leg's origin candle plus a yellow **displacement-leg** box; closed-through zones flip to **BREAKER**. |
| Imbalances | FVG → **IFVG** flip when price closes through. |
| Fibonacci | Auto fib on the active structure leg: 0 / 23.6 / 38.2 / 50 / 61.8 / 65 / 71 / 78.6 / 88.6 / 100 (editable) + OTE shading. 100% = origin of the leg, 0% = its extreme. |
| Volume profile | Lookback histogram split into buy (blue) / sell (red) volume, value area highlighted, POC level. Optional previous-day POC/VAH/VAL. |
| Extras | Optional swing rejection (wick) zones, EMAs 50/200. |

### Signals & alerts

A ▼ / ▲ label prints when a **closed** candle wicks through a level (or into a zone)
and closes back on the other side, with a wick of at least 35% of the candle (both
configurable). The label names the level(s), e.g. `▼ PDH + 4H SELL ZONE`.
Signals are evaluated on bar close only, so they don't repaint.

Alerts: *Bearish / Bullish rejection / sweep*, *Bullish / Bearish BOS*, plus a dynamic
`alert()` message naming the level (create the alert with "Any alert() function call").

### Dashboard

Bias (price vs daily & weekly open), last BOS direction, active session, nearest
resistance/support with distance, day range vs ATR, and **signal stats**: every
signal is tracked with the stop just beyond the rejection wick and a target at a
fixed R multiple (default 1:2); a bar that touches both counts as a loss. It's a
quick, honest read of how the rejections on *your* symbol/timeframe actually
played out — check it before trusting any "90% win rate" claim.

### Notes

- Day/session levels need an intraday chart; weekly levels need ≤ daily.
- HTF inputs must be ≥ the chart timeframe (they're ignored otherwise).
- Everything is toggleable; if the chart feels busy, turn off session boxes,
  round numbers or the volume profile first.

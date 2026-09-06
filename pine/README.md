# Pine Script

TradingView ports of the KCharts indicators.

## `phantom-flow.pine`

The `Phantom Flow SMC` overlay (`src/indicators/smc.ts`) rewritten for TradingView,
plus the volume-profile block the web engine doesn't draw.

**Install:** TradingView → Pine Editor → paste the file → *Save* → *Add to chart*.

### What it draws

| Layer | Detail |
| --- | --- |
| Swing structure | Fractal pivots tagged `HH` / `HL` / `LH` / `LL` |
| Market structure | `BOS` on continuation, `CHoCH` (dashed) on reversal |
| Order blocks | Last opposite candle before a break; the zone stays open and keeps extending right until price mitigates it, then freezes |
| Fair value gaps | 3-candle imbalances, open until filled |
| Liquidity | Equal highs / lows joined by a dashed line, with a circle on both pivots |
| Volume profile | Lookback-range profile split into up/down volume, value area highlighted, POC line |
| Price scale | POC, VAH, VAL and the last swing high/low published as axis labels |
| Read-out | Top-left box with trend, POC, VAH, VAL |

### Settings that matter

- **Swing strength** (default 5) — the single biggest knob. Higher = fewer, more
  significant structure points. Same `swing` parameter as the TypeScript engine.
- **Lookback (bars)** (default 240) — the profile's range. Pine has no access to
  the actual visible range, so this is a fixed window ending at the last bar;
  set it to roughly what you keep on screen.
- **Rows** (default 28) — profile resolution.
- **Value area %** (default 70) — grown out from the POC, taking the fatter
  neighbouring row each step.
- **Width (% of lookback)** (default 16) — how far the profile bars reach left
  from the right edge. Boxes always render *above* candles in TradingView, so
  keep this modest or the profile covers price action.
- **Read-out position** (default top right) — top left collides with the DOM /
  order panel on a trading layout.
- **Equal tolerance (%)** (default 0.1) — how close two pivots must be to count
  as a liquidity pool.

### Alerts

Two conditions ship with it: *Bullish structure break* and *Bearish structure
break*, both firing on BOS **and** CHoCH.

### Notes / limits

- The profile recomputes on the last bar only, on every tick. That keeps it cheap
  but means it does not repaint history — there is no per-bar profile.
- Volume is split across the rows each bar's high–low range covers, weighted
  evenly. That's the standard approximation; TradingView's own VRVP does the
  same unless you feed it lower-timeframe data.
- On symbols with no volume feed the profile bars collapse to nothing; the
  structure layers still work.
- A zone is never mitigated by the bar that created it — the impulse candle
  routinely overlaps the block it just left behind. Order blocks close on first
  touch of the zone; gaps close only when fully filled. Both match
  `src/indicators/smc.ts`, which starts its mitigation scan at `breakBar + 1`.

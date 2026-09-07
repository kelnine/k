# Pine Script

TradingView ports of the KCharts indicators.

## `phantom-flow.pine`

The `Phantom Flow SMC` overlay (`src/indicators/smc.ts`) rewritten for TradingView,
plus a volume profile with per-row order-flow delta.

**Install:** TradingView → Pine Editor → paste the file → *Save* → *Add to chart*.

### What it draws

| Layer | Detail |
| --- | --- |
| Swing structure | Fractal pivots tagged `HH` / `HL` / `LH` / `LL` |
| Market structure | `BOS` on continuation, `CHoCH` (dashed) on reversal |
| Order blocks | Last opposite candle before a break; the zone stays open and keeps extending right until price mitigates it, then freezes |
| Fair value gaps | 3-candle imbalances, open until filled |
| Liquidity | Equal highs / lows joined by a dashed line, with a circle on both pivots |
| Volume profile | Two styles — see below — over the visible range or a fixed window, with value area and POC |
| Price scale | POC, VAH, VAL and the last swing high/low published as axis labels |
| Read-out | Corner box with trend, POC, VAH, VAL and net delta |
| Trade marker | Optional entry → exit arrow labelled in R |

### Profile styles

**Profile style** switches the renderer; both read the same per-row buy/sell numbers.

- **Delta grid** (default) — total volume as a grey histogram, plus a separate
  column marking rows where one side holds at least *Imbalance threshold %* of
  the volume, and the signed delta printed alongside. Footprint-sidebar style.
- **Classic bars** — buy and sell volume stacked into one bar per row, growing
  left from the profile's right edge. Rows outside the value area are dimmed.

### Delta source

- **Intrabar (precise)** (default) — splits each bar's volume using
  lower-timeframe candles via `request.security_lower_tf`. The most accurate
  option, and the most expensive; *Intrabar timeframe* on `Auto` picks a
  sensible sub-resolution for the chart timeframe.
- **Close position** — estimates the buy share from where the bar closed in its
  own range.
- **Bar direction** — all of an up bar's volume counts as buying, all of a down
  bar's as selling.

TradingView caps how much intrabar data a script may pull, so on a deep window
the oldest bars silently fall back to the *Close position* estimate.

### Settings that matter

- **Swing strength** (default 5) — the single biggest knob. Higher = fewer, more
  significant structure points. Same `swing` parameter as the TypeScript engine.
- **Profile covers** — *Visible range* rebuilds from what is on screen and
  re-runs on every pan/zoom; *Last N bars* pins it to a fixed window.
- **Hard bar cap** (default 1200) — the safety valve. A fully zoomed-out chart
  can otherwise ask the script to bin tens of thousands of bars.
- **Rows** (default 28) — profile resolution.
- **Value area %** (default 70) — grown out from the POC, taking the fatter
  neighbouring row each step.
- **Placement / Width** — *Right of bars* uses the empty space after the last
  candle; *Over the bars* keeps the profile inside the range, where boxes will
  render on top of price (TradingView cannot draw them behind).
- **Equal tolerance (%)** (default 0.1) — how close two pivots must be to count
  as a liquidity pool.
- **Read-out position** (default top right) — top left collides with the DOM /
  order panel on a trading layout.

### Alerts

Two conditions ship with it: *Bullish structure break* and *Bearish structure
break*, both firing on BOS **and** CHoCH.

### Notes / limits

- The profile is rebuilt on the last bar from completed bars, so panning and
  zooming just re-runs the same maths — no repainted history. It does mean
  there is no per-bar profile.
- Volume is spread across the rows each candle's high–low range covers,
  weighted evenly.
- On symbols with no volume feed the profile collapses to nothing; the
  structure layers still work.
- A zone is never mitigated by the bar that created it — the impulse candle
  routinely overlaps the block it just left behind. Order blocks close on first
  touch of the zone; gaps close only when fully filled. Both match
  `src/indicators/smc.ts`, which starts its mitigation scan at `breakBar + 1`.
- Structure is drawn in arrears by construction: a pivot needs `swingLen` bars
  on its right to confirm, so a swing high is only recognised that many bars
  after it printed.

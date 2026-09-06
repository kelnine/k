# Pine Script indicators

TradingView versions of the KCharts overlays. Paste a `.pine` file into
**Pine Editor → new indicator → Save → Add to chart**.

## `tron-grid-profile.pine` — Tron Grid: Volume Profile + Delta

The right-hand order-flow sidebar: a horizontal volume profile for the range
you are looking at, with per-price-level delta printed and colour-coded next to
it, plus POC / value-area levels and an optional trade marker.

| What you see | Where it comes from |
| --- | --- |
| Grey horizontal bars | Volume traded at each price row over the range |
| Brighter grey rows | Inside the value area (default 70 % of volume) |
| Orange row + dotted line | POC — the highest-volume row; also tagged on the price scale |
| Green / violet blocks | Rows where buyers / sellers hold ≥ the imbalance threshold |
| `+1.2K` / `-340` text | Signed delta (buy − sell volume) for that row |
| Footer `V … Δ … n bars` | Range totals |
| Blue arrow + `+2.78R` | Optional manual trade marker |

### Settings that matter

**Range** — `Visible range` rebuilds the profile from whatever is on screen, so
it follows you as you scroll and zoom; `Last N bars` pins it to a fixed window.
`Hard bar cap` stops a fully zoomed-out chart from timing the script out.

**Delta source**

- `Intrabar (precise)` — splits each chart bar's volume using lower-timeframe
  candles (`request.security_lower_tf`), which is what makes the buy/sell split
  real rather than inferred. `Auto` picks a sane intrabar timeframe: 15m for 4h+
  charts, 5m for 1h+, 3m for 15m+, 1m for 5m+, seconds below that. Seconds data
  needs a plan that carries it — if it is unavailable, or the intrabar timeframe
  is not lower than the chart's, the script silently falls back to the
  `Close position` estimate.
- `Close position` — buy share = `(close − low) / (high − low)`.
- `Bar direction` — up bar counts fully as buying, down bar fully as selling.

Intrabar requests are capped by TradingView at ~100k intrabars, so keep
`N bars` × intrabars-per-bar under that or the profile silently shortens.

**Imbalance threshold %** — a row is flagged when one side holds at least this
share of its volume (58 % is a light filter, 70 %+ only shows the lopsided
rows). **Ignore rows below % of POC volume** drops thin rows so the sidebar does
not fill with noise. **Print delta on** switches the numbers between imbalanced
rows only, every row, or off.

**Profile** — `Rows` is the price resolution. `Width` defaults to **% of range**
(20 %), so the sidebar scales with however many bars you are looking at instead
of swamping a zoomed-in chart; switch to `Fixed bars` if you want it pinned.
The histogram takes the left ~68 % of that width, the delta blocks the rest, and
the delta numbers print in the gutter just past the block so the text never sits
on top of the bars — `Text size` can go up to Large without anything colliding.

`Placement` decides where the block sits:

- `Right of bars` (default) — in the empty space after the last candle, like the
  original. TradingView extends the time axis to fit it, which squeezes the
  candles left; keeping the width percentage modest is what stops that hurting.
- `Over the bars` — inside the range, hugging the right edge, so the chart's
  scaling is untouched. Raise the histogram transparency if it covers too much
  price action.

### Trade marker

Off by default. Fill in entry/exit time and price to draw the arrow; add a stop
price and it labels the trade in R (`(exit − entry) / (entry − stop)`, direction
inferred from where the stop sits). Times are Unix ms — the settings dialog gives
you a date picker for them.

### Notes

- Pine v6. Everything is drawn on the last bar and wiped on each recalculation,
  so there is no repainting of history: it is the same maths re-run over the
  bars you can see.
- Volume is the exchange's volume for the chart symbol. On spot FX and some
  indices that is tick volume, which makes the profile shape meaningful but the
  absolute delta numbers less so.
- Box/label budget: `Rows` ≤ 120 keeps it under TradingView's 500-object limit.

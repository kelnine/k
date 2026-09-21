# Weekly Sweep Model — Pine Script v6

`weekly-sweep-model.pine` encodes a four-step top-down model for TradingView.
Every step is a gate: no signal prints unless all four agree.

| Step | Rule | Where it's read |
|---|---|---|
| 1 · Bias | A weekly sweep is mandatory. Last week's high or low must be taken. Swept the **low** → long bias; swept the **high** → short bias. | Weekly |
| 2 · Location | Price must be *trading inside* a higher-timeframe key level — an HTF FVG or HTF S/R. | 4H (default) |
| 3 · Confirmation | Market structure shift, or breakout structure, in the direction of the bias. | 15m (default) |
| 4 · Execution | Entry from an inverted FVG (**iFVG**) or a change in state of delivery (**CISD**). | Chart timeframe |

Run it on the **execution timeframe** (1m–5m). Steps 1–3 are pulled from their
own timeframes via `request.security`, so the chart timeframe only drives the
trigger — switching from 1m to 5m does not change the bias or the structure read.

## How each piece is detected

- **Weekly sweep** — previous week's high/low via `request.security("W", …[1],
  lookahead_on)`, which is the non-repainting form: last week's levels are known
  from the first bar of this week. Bias resets every Monday and is set by the
  most recent *first* raid of either side.
- **HTF FVG** — 3-candle imbalance on the HTF (`low > high[2]` bullish,
  `high < low[2]` bearish), kept until price *closes* through it (mitigated).
- **HTF S/R** — the last confirmed HTF swing high/low, widened into a zone by
  `S/R zone width × ATR(14)`.
- **Structure** — a swing-pivot state machine on the structure timeframe.
  A break that *flips* direction is tagged **MSS**; a break in the direction
  structure was already going is **BOS**. Both are accepted by default; turn off
  *Accept BOS* for shift-only.
- **iFVG** — a chart-timeframe FVG that price closes through, which then acts as
  the opposite polarity. Entry fires on the inversion close, or on the retest of
  the inverted zone (input).
- **CISD** — the open of the *first* candle of the run that delivered the last
  move. A close back through that open = delivery changed state.

## Risk

Stop is the swing extreme of the last `Stop: swing lookback` bars ± an ATR
buffer; TP1/TP2 are R-multiples off that distance (2R / 3R by default). Entry,
stop and both targets are drawn on the signal bar.

## Dashboard

The table shows each of the four steps with its current state and an `OK` / `--`
mark, so you can see *which* gate is missing rather than just "no signal". Read
it as a pre-trade checklist.

## Alerts

Two `alertcondition` entries (`WS Model · Long` / `WS Model · Short`) plus a
dynamic `alert()` that includes symbol, price, which POI, MSS vs BOS, and which
trigger fired.

## Repainting

HTF and structure series update only when their own bar closes, so history is
computed on confirmed closes. The currently forming HTF/15m bar can still change
until it closes — that is live price, not hindsight. If you want the strictest
read, act on chart-bar closes and treat the current 15m candle as provisional.

## Install

TradingView → Pine Editor → paste the file → *Add to chart*. Save it to your
scripts so the inputs persist.

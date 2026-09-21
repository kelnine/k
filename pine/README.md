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

---

# Weekly Sweep Model **v2** — `weekly-sweep-model-v2.pine`

A stricter rebuild: ordered state machine, confirmed-bar-only logic, virtual
trade management, full alert set. v1 is kept as the simpler confluence version.

## Provenance of every rule

| Tier | Meaning | In the script |
|---|---|---|
| **[T] Trader-stated** | From the trader's own message | Weekly sweep mandatory + sets direction · price must be inside an HTF key level (S/R or FVG) · 15m MSS / breakout structure · execution via small-TF iFVG or CISD |
| **[O] Post-observed** | From public posts | **None.** `x.com` was unreachable from the build environment; no post content informed any rule. |
| **[A] Assumption** | Added to make it codeable | Everything else — sweep = breach *and* reclaim, all windows/expiries, pivot strengths, ATR padding, stop construction, 2R/4R/BE, strict ordering, re-arm behaviour |

Every `[A]` rule is an input and can be changed or disabled.

## State machine

```
idle ──weekly sweep+reclaim──> wait HTF level ──interaction──> wait 15m structure
                                                                      │
                            virtual trade <──iFVG/CISD── wait execution
```

- Each stage expires after a configurable number of **confirmed 15m bars**.
- An **opposite 15m structure break** cancels a pending setup at any stage.
- A **weekly rollover** expires the bias and cancels a pending setup.
- With *Strict ordering* on (default), each stage must advance on a **later**
  15m bar than the one before, so two stages can never be credited to a single
  candle whose intrabar sequence is unknowable.

## Non-repainting

- Weekly / HTF / 15m data uses `request.security(..., expr[1], lookahead_on)` —
  the documented confirmed-HTF pattern. It reads the **last closed** bar only.
- 15m transitions fire once, on the chart bar where a newly closed 15m bar first
  appears; the ~15 chart bars inside it cannot re-fire the same event.
- Pivots become available only after every right-side bar has closed, and a
  break is credited only to a bar closing **after** that availability. No pivot
  signal is backdated to the visual pivot candle.
- Execution requires `barstate.isconfirmed`.
- **Realtime vs history:** identical, with one nuance — a 15m transition is
  processed on the live chart bar where the closed 15m bar appears. Pine rolls
  back `var` state on each realtime tick, so it is recomputed identically and
  commits at that bar's close.

## Recommended settings

| Setting | Crypto majors | Low-cap alts |
|---|---|---|
| Chart (execution) | 3m or 5m | 5m |
| Key-level TF | 240 (4H) | 240, or D for swing |
| S/R pivot L/R | 3 / 3 | 4 / 4 |
| S/R pad | 0.35 × ATR | 0.5 × ATR |
| Structure pivot L/R | 3 / 3 | 3 / 3 |
| Sweep window | 16 (4 h) | 24 (6 h) |
| Displacement | off | body ≥ 0.8 × ATR |
| Execution | Either | iFVG only |

Raise pivot strength and displacement to cut noise; lower them for more signals.

## What is *not* automated

Target selection against opposing liquidity, partial exits, early discretionary
exits, news/session context, and correlation. The virtual trade is a fixed
2R/4R skeleton with a breakeven move — a measuring stick, not the trader's
management.

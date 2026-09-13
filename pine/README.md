# NQ Goldbach — TradingView build

Two Pine v6 scripts. Same rules, different jobs.

| File | What it is | Use it to |
|---|---|---|
| `goldbach_po3.pine` | Indicator (study) | Trade from, and fire alerts |
| `goldbach_po3_strategy.pine` | Strategy | Judge the edge in TradingView's backtester |

## Install

1. TradingView → **Pine Editor** (bottom panel) → **Open** → *New blank indicator*.
2. Select all, paste the file's contents over it.
3. **Save**, then **Add to chart**.
4. Repeat with the strategy file if you want the backtest numbers.

Both target Pine v6, which is the editor's default.

## What it draws

A power-of-three dealing range is a block of price `3^k` tall, **anchored to
multiples of its own size** — an 81-point range on NQ sits at 29322 / 29403, not
wherever the last swing printed. Nobody has to agree with your swing labelling
for the levels to line up. Because `243 = 3 × 81` the ranges nest, so the script
draws two at once: the one sized to the instrument, and the one three times
larger (faded, only its key levels labelled).

Inside a range, price is partitioned at fixed ratios — each standing for the
structure the algorithm is expected to leave there:

| Ratio | Tag | Meaning |
|---|---|---|
| 0.03 / 0.97 | RB | rejection block |
| 0.11 / 0.89 | OB | order block |
| 0.17 / 0.83 | FV | fair value gap |
| 0.29 / 0.71 | LV | liquidity void |
| 0.41 / 0.59 | BR | breaker |
| 0.47 / 0.53 | MB | mitigation block |
| 0.50 | EQ | equilibrium — premium above, discount below |

plus the `−0.111` / `1.111` extensions either side. Labels read
`0.83 FV | 81`: ratio, what it is, which range it belongs to.

The right-hand gutter carries the **premium / discount column**, banded by the
partition itself: red above equilibrium, green below, deepening toward the
extremes. On top of that the script marks BOS / CHoCH breaks, order blocks and
fair value gaps (each extended until price closes through it), and an EMA pair.

### PO3 sizing

`Auto` picks the smallest power of three that comfortably contains a typical
bar's range (median true range over 100 bars × 1.2) — 81 on NQ intraday, much
larger on BTC. Override it from the dropdown when you want a fixed range.

## What the bot does

| | |
|---|---|
| **Bias** | structure: a close through the last confirmed swing (BOS / CHoCH) |
| **Filter** | price must be on the bias side of equilibrium — longs in discount, shorts in premium |
| **Entry** | a limit resting on the nearest OB / FV / RB / LV level, if it is within `reach × ATR` |
| **Cancel** | after `orderLife` bars, or when the bias flips against it |
| **Stop** | `stopAtr × ATR(14)` from the fill |
| **Targets** | half off at T1 (1R), the rest at T2 (2R); stop to break-even after T1 |
| **Size** | account equity × risk %, divided by stop distance × point value |

It never chases. If price doesn't come back to the level, the order is pulled
and it waits for the next one. The resting order is drawn as its ticket
(`10 | Buy Limit · 0.83 FV | 81`); a fill draws entry / stop / target lines with
the risk and reward boxes, and the close prints the R multiple.

## Alerts

Every step calls `alert()`, so one alert covers the lot:

1. Right-click the chart → **Add alert**.
2. Condition: **NQ Goldbach**, then **Any alert() function call**.
3. Put your webhook URL in the *Notifications* tab if a bot is listening.

Messages are ready to parse, e.g.
`BUY LIMIT 10 NQ1! @ 29379.75  (0.83 FV | 81)  stop 29331.25`.

There are also five named `alertcondition` entries (limit placed, filled, T1,
T2, stopped) if you prefer one alert per event.

## What this cannot do

- **An indicator cannot place orders.** It signals; your alert, webhook or
  broker integration does the rest. The `10 | Buy Limit` ticket is a drawing of
  an intention, not a working order at your broker.
- **The R multiples on the indicator are not a backtest.** They track one
  position at a time with no costs. Run the strategy build for real statistics,
  with your own commission and slippage filled in.
- Orders are placed on **confirmed bars only**, so signals don't repaint;
  fills are evaluated against each bar's high/low, so on the live bar a fill
  appears the moment price touches the level.
- Nothing here is a forecast, and none of it has been tested against real NQ
  data by its author — check it on your own instrument and timeframe before
  putting size on it.

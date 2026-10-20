# smc_sniper — Smart Money Suite v4 sniper: BOS + score, 2R (S3)

Port of the sniper of `terminal/pine/received/05_smart_money_suite_v4.pine`
("Smart Money Suite v4 [AlgoAlpha]"), spec
`terminal/pine/specs/05_smart_money_suite_v4.md`, doc 13 strategy **S3**. The
script is an indicator: on a sniper bar it draws a label with SL and TP and
fires an alert, but tracks no position. Line numbers below are the received
file's. Only the sniper and what feeds it are ported; the breakout channel,
volume sentiment, supply/demand zones, liquidity sweeps, key levels, Fib zone,
high-confluence alert, scanner and dashboard are display or alert only (doc 13
D12).

## Rules

Evaluated on every closed bar in the script's order:

| Rule | Pine | Port |
|---|---|---|
| Indicators | L128 `atr_val = ta.atr(14)`; L174-175 `ta.ema(close, 50/200)`; L584 `ta.rsi(close, 14)` | `Atr`, `Ema`, `Rsi`, each updated on every bar |
| Trend point | L179-180: `close > ema50 and ema50 > ema200` (`<`, `<` for bears) | `gt`/`lt` (1e-10 tolerance, false while an EMA is na: no trend point before 200 bars) |
| Order blocks | L283-313: `ta.pivothigh/low(10, 10)` on every bar; a confirmed pivot **low** whose candle is bearish (`open[10] > close[10]`) pushes the candle's **body** as a bullish block; a pivot **high** with a bullish candle a bearish one; `while size >= 3: shift` before the push | `PivotHigh/PivotLow(ob_len, ob_len)`; `zones.order_block`, `ZoneList(ob_max)`. A pivot with a same-coloured candle gives no block |
| Fair value gaps | L334-356: `high[2] < low` → bullish gap `high[2]`…`low`; `low[2] > high` → bearish gap `high`…`low[2]`; at most 4 per side | `zones.fair_value_gap`, `ZoneList(fvg_max)`; strict, no minimum size |
| Zone deletion | L315-327, L358-370: after the pushes, a bullish zone is deleted on `close < bottom − 0.05 × atr_val`, a bearish one on `close > top + 0.05 × atr_val` — the **current** bar's ATR | `ZoneList.invalidate`; nothing is deleted while the ATR is na; a partial fill keeps a gap |
| Swings | L375-393: `sw_hi = ta.pivothigh(high, 40, 40)`, `sw_lo = ta.pivotlow(low, 40, 40)`; `lsh`/`lsl` take the latest confirmed value, 40 bars after the pivot, and are **never consumed** | `PivotHigh/PivotLow(bos_len, bos_len)`; ties: the newer of equal extremes (doc 14) |
| BOS | L385-396: `cx_up = ta.crossover(close, lsh)`, `cx_dn = ta.crossunder(close, lsl)` are evaluated **before** this bar's swing update; `bos_bull = not na(lsh) and cx_up` | `Crossover`/`Crossunder` updated with `lsh`/`lsl` as they stand before the update, so their `[1]` side is the level as passed on the previous bar, not its end-of-bar value (no phantom BOS on the bar after a new swing confirms; tested) |
| Structure point | L382, L397-403: `var upt = true`; a bullish BOS sets it, a bearish one clears it; CHoCH = a BOS against `upt` | Same; the point is `upt` (`not upt` for bears) **after** this bar's BOS, so on a BOS bar it always counts |
| Zone point | L594-623: the close inside any listed block or gap of its side, `>=` and `<=` | `ZoneList.containing` with `ge`/`le` |
| Momentum point | L585-587: `rsi > 55 and close − close[5] > 0` (`< 45`, `< 0`) | Same; na for the first 5 bars |
| Signal | L625-629: `sniper_long = sniper_bull >= sniper_min and bos_bull` (short mirrored) | Same, on the closed bar |
| Bracket | L645-646: stop `(lsl if not na else low) − 0.5 × atr_val`, target `close + 2 × (close − stop)`; L659-660 short: `(lsh or high) + 0.5 × atr_val`, `close − 2 × (stop − close)`. `lsl`/`lsh` include this bar's update | Same values, from the signal bar, fixed for the life of the trade |

Each signal carries the script's numbers in `metadata`: `pine_signal`
(`sniper_long` / `sniper_short`), `trigger` (`Sniper Long` / `Sniper Short`,
the alert titles), `structure_label` (`BOS` / `CHoCH`, the label the script
draws on that bar), `broken_level`, `score`, `sniper_min`, the four `points`,
the `zones` holding the close (kind, top, bottom, bar index), `stop_basis`
(`swing_low` / `swing_high`, or `bar_low` / `bar_high` before a swing exists),
`ema50`, `ema200`, `rsi`, `roc`, `atr`, `lsh`, `lsl` and their pivot bar
indexes, `bar_index`, `script_entry/stop/target` (unrounded) and
`risk_distance` (|close − stop|, the size of the risk the account must fit).
The reason is `Sniper Long 3/4` etc.

## Params

| Param | Pine input | Default |
|---|---|---|
| `sniper_min` (1-4) | `sniper_min`, "Min Score (1–4)" (L12) | 3 |
| `fvg_on` | `fvg_on`, "Show Fair Value Gaps" (L18): off removes gaps from the zone point | true |
| `fvg_max` (1-8) | `fvg_max`, "Max FVGs Each Side" (L19) | 4 |
| `ob_on` | `ob_on`, "Enable Order Blocks" (L79): off removes blocks from the zone point | true |
| `ob_len` (≥ 3) | `ob_len`, "OB Pivot Lookback" (L80) | 10 |
| `ob_max` (1-8) | `ob_max`, "Max OBs Each Side" (L81) | 3 |
| `bos_len` (≥ 5) | `bos_len`, "Swing Length" (L88) | 40 |
| `smb_atr` (≥ 1) | `smb_atr`, "ATR Length" (L53): the ATR of the stop and of zone deletion | 14 |

`sniper_on` and `bos_on` are not params: either one off disables every
signal. EMA 50/200, RSI 14 with 55/45, the 5-bar ROC, the 0.5 ATR stop offset
and the 2R target are fixed in the script and are constants here. The other
inputs (channel, volume, supply/demand, key levels, sweeps, scanner, colours)
do not change sniper signals.

## Variants and instances (`config/instances.d/smc_sniper.yaml`)

| Instance | Timeframe | Min Score |
|---|---|---|
| `smc_sniper_min3_15m` | 15m | 3 (the script's default) |
| `smc_sniper_min4_15m` | 15m | 4: with the BOS, trend, zone and momentum all required |
| `smc_sniper_min3_5m` / `smc_sniper_min4_5m` | 5m | 3 / 4 |

All 14 instruments (D10), script defaults otherwise (D13), one Paper 50K
account per instance with `max_open_positions: 14` (one position per
instrument). On a BOS bar the structure point always counts, so Min Score 3
needs two of trend, zone and momentum and Min Score 4 all three; Min Score 4
signals are rare (none in three synthetic days on 15m).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| Entries fill at the **next bar's open**; stop and target stay at the script's levels from the signal close | The lab's fill model (doc 13 D3): the levels match the label the user sees |
| An entry whose fill bar opens at or beyond its stop or target is skipped (`ORDER_CANCELLED`, `OPEN_BEYOND_STOP` / `OPEN_BEYOND_TARGET`; meta `skip_entry_beyond_levels`) | Doc 13 D3 |
| A signal whose rounded stop is not beyond the signal close is not traded: a persisted `NO_TRADE` with reason `STOP_WRONG_SIDE` and the script's metadata (`TARGET_WRONG_SIDE`, `LEVELS_NA` while the ATR is na, `LEVELS_NOT_POSITIVE` likewise) | Doc 13 D3. The script never checks its stop (L645, L659): after a fast reversal, before a new swing confirms, the stale `lsl` sits above a long's close (or `lsh` below a short's) and the label shows SL and TP swapped |
| A new signal while in a trade — same direction or opposite — is ignored (meta `on_opposite_signal: ignore`); it is still emitted and recorded | Doc 13 D4 for script 5. The script keeps no position and only replaces its label (L636-667); because levels are never consumed, repeated signals on the same swing are common |
| A trade ends only at its stop or target (stop first when one bar reaches both); held through sessions and weekends | The script has no time exit (doc 13 D6: hold as the script does); the lab's conservative bar resolution |
| Prices are rounded to the instrument's tick for the order | The lab trades on the tick grid; `metadata.script_*` keep the script's unrounded numbers |

A bullish and a bearish sniper signal cannot fire on the same bar: crossing
over `lsh` and under `lsl` together needs `close[1] <= lsh[1]`,
`close[1] >= lsl[1]`, `close > lsh` and `close < lsl`, which is only possible
if a level changed on the previous bar — and a swing confirmed on that bar
lies strictly beyond that bar's own close. Were it to happen, the book would
keep the later (short) entry, as the script's label does.

## Sizing caveat

The stop sits beyond the latest **40/40 swing**, wherever it is, plus 0.5
ATR. Those swings can be far from the entry: at 0.5 % risk on a 50K account
($250), an MNQ stop wider than 125 points cannot be sized to one contract,
and some FX, metal and crypto stops give positions below the venue minimum.
Such entries are rejected by the account and recorded (doc 13 §13.8);
`metadata.risk_distance` shows the distance for each signal.

## Parity notes

* **Cross semantics.** The crosses keep their own history of `lsh`/`lsl` as
  passed (doc 14, `Crossover`); a port using the variables' end-of-bar values
  would see different BOS bars right after a swing confirms. Verify on bars
  right after a pivot confirmation when a chart export is available.
* **Pivot ties.** Equal highs/lows: the newer is the pivot (doc 14, reported
  by PyneCore, unverified by us) for all three pairs (40/40 swings, 10/10
  blocks).
* **History start.** `upt` starts true, `lsh`/`lsl` start na and the zone
  lists fill from the first bar; EMA200 and the Wilder RSI/ATR depend on where
  history starts. Compare with TradingView only after ≥ 1000 bars on the same
  feed.
* **Display toggles change signals** on TradingView: "Show Fair Value Gaps"
  and "Enable Order Blocks" off remove zones from the score; the port mirrors
  them as `fvg_on` / `ob_on` (D13: the defaults, both on).
* **Realtime.** The script has no `barstate.isconfirmed` gate, so its label
  and alert can appear and vanish intrabar on TradingView; only
  close-confirmed signals compare with the lab.
* **Not checked against TradingView**: TradingView is not reachable from the
  development environment and no exports were provided. Correctness is shown
  by golden scenarios and by an independent array-based transcription of
  L128-L660 run against the port on synthetic data
  (`tests/unit/strategies/smc_sniper`).

## Warm-up

`meta.warmup_bars = 1000` (spec: ≥ 600 for EMA200, the Wilder RSI/ATR, the
81-bar swing windows and the zone lists). 1000 bars of 15m are 10.4 days
round the clock and about 15 calendar days on markets that close at weekends,
so with the default `forward.warmup_days: 10` a 15m instance starts short
(`paper.warmup_short` is logged) and its first signals rest on a less
converged EMA200 and on fewer known swings; the 5m instances are fully warmed
up. `forward.warmup_days: 16` in `lab.yaml` would cover the 15m instances.

# psar_ema200 — 200 EMA filtered Parabolic SAR (S8)

Port of the PSAR section (L563-638) of
`terminal/pine/received/04_combined_smc_suite.pine` ("Combined SMC Suite"),
spec `terminal/pine/specs/04_combined_smc_suite.md`, doc 13 strategy **S8**.
**This section was rebuilt by the script's author from screenshots of the
original indicator's settings panel** (L7-8): the rules below are that
reconstruction, not the original code. The script defines entries and a flip
exit but no stop; the stops below are the doc 13 D5 defaults. Line numbers are
the received file's.

## Rules

| Rule | Pine | Port |
|---|---|---|
| Indicators | L602-605: `ta.ema(close, 200)`, `ta.sar(0.02, 0.02, 0.2)`, `ta.dmi(14, 14)` | `Ema(200)`, `Sar(0.02, 0.02, 0.2)` (exact `pine_sar`: projection tested before the clamp, bar-1 start), `Dmi(14, 14)` |
| Flip | L607-611: `psSarBull = psSar < close`, `psFlipUp = psSarBull and not psSarBull[1]` (bear mirrors) | Same, with Pine comparisons; `psSarBull[1]` is false before the first bar. The flip is the SAR crossing the **close**, not the SAR's internal trend |
| Filters | L613-615: `close > psSlow` / `close < psSlow`, `psAdx > 20` (strict) | Same (`gt`/`lt`, 1e-10 tolerance) |
| Exit | L620-627: `psExitLong = psInLong and psFlipDn` (short mirrors), from the state carried in from the previous bar; the filters do not apply | `PsarState` keeps the script's `psInLong`/`psInShort`; on an exit bar the matching position closes at the next open (`EXIT_*`, metadata `EL`/`ES`) |
| Entry | L630-638: `psLong = psFlipUp and psTrendUp and psStrongT and not psInLong` (short mirrors) | Same. Only the flip bar can enter: a leg whose flip bar fails a filter is never traded |
| Reverse | an exit and the opposite entry on one bar | Exit first, then the entry: both at the next open (doc 05 §5.3 *replace*). When the new side's filters fail, the strategy is flat until the next qualifying flip |
| Protective stop (D5) | none | `stop_mode: sar`: fixed at the SAR printed on the signal bar (the previous leg's extreme), never moved |
| Trailed stop (D5 variant) | none | `stop_mode: trail`: the initial stop and every bar's `MOVE_SL` are TradingView's **projected** SAR (`Sar.projected()`: the level whose touch flips the next bar), moved only when that tightens the stop |

Metadata: `trigger` (the marker text `Long`, `Short`, `EL`, `ES`), `pine_signal`
(`psLong`, `psShort`, `psExitLong`, `psExitShort`), `sar`, `projected_sar`,
`sar_is_long`, `ema`, `adx`, `close`, `bar_index`, and on entries `stop_mode`,
`script_entry`, `script_stop`.

## Params

| Param | Pine input | Default |
|---|---|---|
| `ma_slow_length` | `psMaSlowLength` | 200 |
| `psar_start`, `increment`, `maximum` | `psStart` ("PSARstart"), `psIncrement`, `psMaximum` | 0.02, 0.02, 0.2 |
| `di_length`, `adx_smoothing` | `psDiLength`, `psAdxSmoothing` | 14, 14 |
| `threshold` (0-100) | `psThreshold` | 20 |
| `stop_mode` | — (doc 13 D5) | `sar` (`trail`: projected SAR) |

`psMaFastLength`/`psMaMedLength` (7/21) only colour a band (L1057) and are not
ported; nor are the display inputs. The script's other modules (order blocks,
channels, KCharts, DepthFlow) and the PSAR + channel confluence alert stay
levels-only (doc 13 D12).

## Instances (`config/instances.d/psar_ema200.yaml`)

| Instance | Timeframe | Stop |
|---|---|---|
| `psar_ema200_main_15m` | 15m | SAR of the signal bar (D5 main) |
| `psar_ema200_main_5m` | 5m (D10 variant) | SAR of the signal bar |
| `psar_ema200_trail_15m` / `_trail_5m` | 15m / 5m | projected SAR, trailed (D5 variant) |

All 14 instruments (D10), script defaults (D13), one Paper 50K account per
instance with `max_open_positions: 14`. Stop and reverse (D4).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| Entries and exits fill at the **next bar's open** | The lab's fill model; the script's markers sit on the flip bar's close (D3) |
| A protective stop on every entry | The script has none; the lab needs one (D5) |
| An entry whose fill bar opens at or beyond its stop is skipped (`ORDER_CANCELLED` / `OPEN_BEYOND_STOP`); an exit on the same bar still happens | Doc 13 D3 |
| A stop not beyond the entry after tick rounding (possible in `trail` mode, when the projection already lies past the close) is not traded: persisted `NO_TRADE` `STOP_WRONG_SIDE` | Doc 13 D3. The script's state still records the entry, as on the chart |
| After a stop-out the script's state (`psInLong`/`psInShort`) is unchanged: the next opposite flip is a plain entry, and a same-side flip while the script still counts itself in the trade does not re-enter | Faithful to the script, which has no stop |
| In `trail` mode a stop above a long's (below a short's) price is allowed; it fills at the next open | That projection is the level TradingView's SAR flips at; the open is already past it |

## Parity notes

* `ta.sar` starts from the second bar of history and its path depends on it
  until the first reversal; EMA200 and the Wilder ADX need ≥ 1000 bars. The
  script's state (`psInLong`) also starts flat on the first bar.
* When the SAR equals the close the bar is neither bull nor bear, so the next
  bar can register a flip without a SAR reversal (L607-611); the port keeps it.
* SAR flip bars are usually wide: the gap between the flip close and the next
  open is material.
* A stop at the signal bar's SAR can be far away: on some instruments the
  account sizes such trades to the minimum or rejects them (doc 13 §13.8).
* **Not checked against TradingView** (not reachable from the development
  environment, no exports provided). Correctness is shown by golden scenarios
  and by an independent transcription of L600-638 compared on long synthetic
  runs (`tests/unit/strategies/psar_ema200`).

## Warm-up

`meta.warmup_bars = 1000` (spec: ≥ 1000 for EMA200 and ADX(14, 14)). With the
default `forward.warmup_days: 10` a 15m instance gets fewer bars than that on
markets that close at weekends (`paper.warmup_short`).

## Licence

The script names LuxAlgo (CC BY-NC-SA 4.0) and AlgoAlpha (MPL 2.0) for its
order-block and channel sections; this port uses neither. The PSAR
reconstruction carries no licence statement (doc 13 §13.8: private use).

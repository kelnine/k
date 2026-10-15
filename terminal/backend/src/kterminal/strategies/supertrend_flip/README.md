# supertrend_flip — Jetstream v2 SuperTrend (10, 3) flip (S7)

Port of the BUY/SELL and BUY+/SELL+ signals of
`terminal/pine/received/10_jetstream_v2.pine` ("Jetstream v2"), spec
`terminal/pine/specs/10_jetstream_v2.md`, doc 13 strategy **S7**. The script is
an indicator with no stop, target or position; the exits and stops below are
the doc 13 D5 defaults. Line numbers are the received file's.

## Rules

| Rule | Pine | Port |
|---|---|---|
| Trend | L121: `[st, dir] = ta.supertrend(3.0, 10)` | `SuperTrend(3.0, 10)` (exact `pine_supertrend`: hl2 bands, ratchet, `nz(prev) = 0` start, close vs the current bar's band) |
| BUY / SELL | L166-168: `flip = ta.change(dir)`; `tBuy = flip < 0 and buyOK`, `tSell = flip > 0 and sellOK` | `Change(1)` of the direction; `buyOK`/`sellOK` are true (the HTF filter is off by default, L30) |
| BUY+ / SELL+ | L147-151, L169-170: WaveTrend of `hlc3` (10, 21, 4); `strongBuy = tBuy and wt1 < 0`, `strongSell = tSell and wt1 > 0` | `WaveTrend(10, 21, 4)` (`ci` is 0, not na, while `de` warms up); Pine comparisons, so `wt1 == 0` or na is not strong |
| Entry (D5) | none: the label is drawn on the flip bar, so the implied price is its close | On the closed flip bar, `signals: all` enters every BUY (long) / SELL (short); `signals: strong` only BUY+ / SELL+ |
| Exit (D5) | none: the next opposite flip is the implied exit | Any opposite flip closes the position at the next open (`EXIT_*`, reason `SuperTrend flip (…)`), then the new side enters at that same open (doc 05 §5.3 *replace*). In `strong` mode a plain opposite flip exits flat |
| Protective stop (D5) | none | Fixed at the signal bar's line ∓ `stop_atr_mult` × ATR(10) (default 1 ATR), no target |
| Trailed stop (D5 variant) | none | `trail_stop: true`: every bar the stop moves (`MOVE_SL`) to the line ∓ `stop_atr_mult` × ATR, only when that tightens it; the variant instances use `stop_atr_mult: 0`, i.e. the line itself |

Metadata: `pine_signal` (`tBuy`, `strongBuy`, `tSell`, `strongSell`), `trigger`
(the label text `BUY`, `BUY+`, `SELL`, `SELL+`), `strong`, `supertrend`,
`direction`, `flip`, `atr`, `wt1`, `wt2`, `bar_index`, and on entries
`script_entry`, `script_stop`, `stop_atr_mult`, `trail_stop`.

## Params

| Param | Pine input | Default |
|---|---|---|
| `atr_len`, `mult` | `atrLen`, `mult` | 10, 3.0 |
| `n1`, `n2`, `sig_len` | WaveTrend `n1`, `n2`, `sigLen` (source fixed at `hlc3`, the script's default) | 10, 21, 4 |
| `signals` | — (doc 13 D11) | `all` (`strong`: BUY+/SELL+ only) |
| `stop_atr_mult` (≥ 0) | — (doc 13 D5) | 1.0 |
| `trail_stop` | — (doc 13 D5 variant) | false |

Display inputs (EMA ribbon, MACD, money flow, volume heatmap, take-profit
diamonds, divergences, supply/demand zones, scanner, dashboard) do not change
the BUY/SELL signals and are not ported.

## Instances (`config/instances.d/supertrend_flip.yaml`)

| Instance | Signals | Stop |
|---|---|---|
| `supertrend_flip_all_5m` / `_all_15m` | every flip | line ∓ 1 ATR(10), fixed (D5 main) |
| `supertrend_flip_strong_5m` / `_strong_15m` | BUY+ / SELL+ (exit on any opposite flip) | line ∓ 1 ATR(10), fixed |
| `supertrend_flip_trail_5m` / `_trail_15m` | every flip | on the line, trailed every bar (D5 variant) |

All 14 instruments (D10), one Paper 50K account per instance with
`max_open_positions: 14`. Stop and reverse (`on_opposite_signal: reverse`, D4).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| Signals on **closed** bars only; entries and exits at the next open | The script's labels and alerts are not confirmation-gated (L166-172) and can flash intrabar; a closed-bar port matches TradingView's historical bars and "once per bar close" alerts. Next-open fills are the lab's model (D3) |
| A stop on every entry, and exits on the flip | The script defines neither; the lab needs a stop (doc 13 D5) |
| An entry whose fill bar opens at or beyond its stop is skipped (`ORDER_CANCELLED` / `OPEN_BEYOND_STOP`); the flip's exit still happens | Doc 13 D3 |
| A stop that is not beyond the entry after tick rounding, or not positive, is not traded (persisted `NO_TRADE`: `STOP_WRONG_SIDE`, `STOP_NOT_POSITIVE`, `STOP_NA`) | Doc 13 D3 |
| No **4H HTF-filter** variant (`useHTF`, L30, L123-126) | It needs 4H bars anchored to the instrument's session (TradingView's grid); the market-data layer does not build them yet (doc 13 P5, open). Off by default in the script |
| Take-profit diamonds are ignored | The script calls them a "consider trimming" hint, not an exit (L41) |

## Parity notes

* SuperTrend is path-dependent (ratchet from a zero start, direction forced to
  1 while the ATR warms up): compare flips with TradingView only after the
  first flip that follows a long warm-up.
* The trailed variant is a different strategy from the chart: a wick through
  the line exits before the close-confirmed flip, which then finds it flat.
* Always in the market (main instances): swap/funding is charged by the cost
  model (doc 13 §13.8).
* **Not checked against TradingView** (not reachable from the development
  environment, no exports provided). Correctness is shown by golden scenarios
  and by a comparison with the flips computed directly from the indicator
  classes on long synthetic runs (`tests/unit/strategies/supertrend_flip`).

## Warm-up

`meta.warmup_bars = 500` (spec: ≥ 300 for ATR(10), the band ratchet and the
WaveTrend EMAs).

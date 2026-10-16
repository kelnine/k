# 14. Pine-parity indicators

`kterminal.indicators` reproduces the TradingView `ta.*` built-ins (and the
few Pine language rules around them) that the received scripts call, so a
Python port computes the same values as the chart it came from. It is item P3
of the Phase 3 plan and the indicator half of P4 ([doc 13](13-phase3-pine-ports.md#133-what-the-engine-still-needs));
fair value gaps, order blocks, sweeps and CISD rules stay inside each
strategy because every script defines them differently.

## 14.1 How a strategy uses it

Every indicator is a small **streaming object**: the strategy creates it in
`on_start` and updates it once per closed bar.

```python
from kterminal.indicators import Atr, Crossover, Ema, na

class EliteAlgo(Strategy[Params]):
    def on_start(self) -> None:
        self.ema_fast, self.ema_slow = Ema(8), Ema(21)
        self.atr = Atr(14)
        self.cross_up = Crossover()

    def on_bar(self, bar: Bar) -> SignalOutput:
        close = float(bar.close)
        fast = self.ema_fast.update(close)          # math.nan while Pine returns na
        slow = self.ema_slow.update(close)
        atr = self.atr.update(float(bar.high), float(bar.low), close)
        if self.cross_up.update(fast, slow) and not na(atr):
            ...
```

Rules that apply to every class:

| Rule | Why |
|---|---|
| **One object per Pine call site**, updated on *every* bar from the first bar on — also on bars where the result is not used | A Pine built-in keeps its own history of the arguments it was called with. Called only inside an `if`, it sees only those bars; so does the object. Calling it every bar is what matches a script that calls it unconditionally |
| **Call `update` where the script calls the function**, with the values the script has at that point | The object's `[1]` is the value *as passed* on the previous bar, not a variable's end-of-bar value (script 5's `ta.crossover(close, lsh)` runs before `lsh` is reassigned) |
| **Float64** in, float64 out | Pine computes in doubles. Convert `Decimal` prices with `float()` on the way in and back to `Decimal` at the `Signal` (doc 01 §1.10) |
| **na is `math.nan`** | `update` returns `nan` wherever Pine returns `na`; `None` and ±infinity count as na on input (Pine has no infinity: `1 / 0` is na). Use `na()`, `nz()`, `FixNan` and `div()` as in Pine |
| The last result is also in **`.value`** | So one place can update and another read |
| Objects use `__slots__` and hold only their own state | Two instances never share anything; a misspelt attribute raises instead of silently creating state |

`feed(update, *columns)` runs an object over whole lists (tests, parity
reports): `feed(Atr(14).update, highs, lows, closes)`.

## 14.2 Reference

"First value" is the 0-based bar index of the first non-na result for an
input that is never na.

| Pine | Class / function | Output | First value | na input | Notes |
|---|---|---|---|---|---|
| `na(x)`, `nz(x, r)` | `na`, `nz` | bool, float | — | — | na = nan, None, ±inf |
| `fixnan(x)` | `FixNan` | float | first non-na | carries the last non-na value | one object per call site |
| `x / y` | `div(x, y)` | float | — | na | na when `y == 0` (Python would raise) |
| `>` `>=` `<` `<=` `==` `!=` | `gt` `ge` `lt` `le` `eq` `ne` | bool | — | **false** (also `ne`) | 1e-10 absolute tolerance, see 14.3 |
| `math.round(x)` | `pine_round(x)` | float | — | na | ties **away from zero**: 2.5 → 3, −2.5 → −3; `round()` in Python gives 2 |
| `math.round(x, p)` | `pine_round(x, p)` | float | — | na | integer part kept, fraction rounded; a fraction within 1e-10 (in last-decimal units) below a tie counts as the tie: `2.675 → 2.68` |
| `math.round_to_mintick(x)` | `round_to_mintick(x, tick)` | float | — | na | tick = `ctx.instrument.tick_size`; same tie rule |
| `x[i]` | `History(maxlen)` | `h[i]` | — | stored as is | `h[0]` current bar; beyond the history → na |
| `bar_index` | `BarIndex` | int | 0 | — | |
| `ta.change(x, n)` | `Change(n)` | float | `n` | na if either side is na | raw bar history (na bars included); on a ±1 direction series a flip is ±2 |
| `ta.barssince(c)` | `BarsSince` | float | first true bar | — | 0 on a true bar |
| `ta.valuewhen(c, x, k)` | `ValueWhen(k)` | float | `k+1`-th true bar | a na `x` on a true bar is recorded and counts | held across false bars |
| `ta.cum(x)` | `Cum` | float | 0 | na that bar, adds nothing | plain double accumulation |
| `math.sum(x, n)` | `Sum(n)` | float | `n-1` | **skipped** | exact `fsum` over the window |
| `ta.sma(x, n)` | `Sma(n)` | float | `n-1` | **skipped** | `math.sum / n` |
| `ta.ema(x, n)` | `Ema(n)` | float | `n-1` | **skipped** | α = 2/(n+1); **seed = SMA of the first n values**; step `prev + α(x − prev)` |
| `ta.rma(x, n)` | `Rma(n)` | float | `n-1` | **skipped** | α = 1/n; seed = SMA; step `(prev(n−1) + x)/n` |
| `ta.variance(x, n, biased)` | `Variance(n, biased)` | float | `n-1` | **skipped** | one-pass `max(0, Σx²/n − mean²)`; unbiased length 1 is na |
| `ta.stdev(x, n, biased)` | `Stdev(n, biased)` | float | `n-1` | **skipped** | **population** by default (pandas defaults to ddof 1) |
| `ta.tr`, `ta.tr(true)` | `TrueRange(handle_na)` | float | 1 / 0 | na | first bar: na, or `high − low` with `handle_na` |
| `ta.atr(n)` | `Atr(n)` | float | `n-1` | skipped | RMA of `ta.tr(true)` |
| `ta.rsi(x, n)` | `Rsi(n)` | float | `n` | skipped; change measured from the last non-na value | 100 when the down average ≤ 1e-10 (tested first: a flat series is 100), 0 when the up average ≤ 1e-10 |
| `ta.macd(x, f, s, g)` | `Macd(f, s, g)` | `(macd, signal, hist)` | `s-1`, signal `s+g-2` | skipped | script 9's "pulse" histogram is `Macd(5, 60, 20).hist` |
| WaveTrend (script 10) | `WaveTrend(n1, n2, sig)` | `(wt1, wt2)` | `n2-1` | — | `ci = de != 0 ? … : 0`, so `ci` is 0 (not na) while `de` warms up |
| `ta.dmi(n, s)` | `Dmi(n, s)` | `(plus, minus, adx)` | `n`, ADX `n+s-1` | — | `pine_dmi`; TR without na handling; tolerant DM comparisons; `fixnan` on DI |
| `ta.sar(start, inc, max)` | `Sar(start, inc, max)` | float | 1 | bar skipped | `pine_sar`, see 14.4 |
| `ta.supertrend(f, n)` | `SuperTrend(f, n)` | `(supertrend, direction)` | 0 (= 0.0), then `n-1` | — | `pine_supertrend`, see 14.4; direction −1 = up trend |
| `ta.highest(x, n)`, `ta.lowest` | `Highest(n)`, `Lowest(n)` | float | `n-1` | **resets the window** | ties irrelevant for the value; per-bar `n` supported |
| `ta.highestbars(x, n)`, `ta.lowestbars` | `HighestBars(n)`, `LowestBars(n)` | float ≤ 0 | `n-1` | 0, window reset | equal extremes: the **oldest** bar |
| `ta.pivothigh(x, l, r)`, `ta.pivotlow` | `PivotHigh(l, r)`, `PivotLow(l, r)` | pivot value or na | `l+r` | na, window reset | reported `r` bars late; `>=` left, `>` right; per-bar `l`, `r` supported |
| `ta.crossover(a, b)`, `ta.crossunder` | `Crossover`, `Crossunder` | bool | 1 | false, bar skipped | exact `a > b and a[1] <= b[1]` against the last bar where both were defined |
| `ta.cross(a, b)` | `Cross` | bool | — | false, bar skipped | *not* `crossover or crossunder`, see 14.3 |
| `ta.vwap(x, anchor, mult)` | `Vwap` | `(vwap, stdev)`, `.upper(m)`, `.lower(m)` | first anchor | na that bar, nothing changes | see 14.4 |

## 14.3 na handling, ties and comparisons

**Three na policies**, matching what each built-in does:

* **Skipped (na-compacted)** — `Sum`, `Sma`, `Ema`, `Rma`, `Variance`,
  `Stdev`, `Atr`, `Rsi`, `Macd`: a na input returns na and does not advance
  the state, so the result always covers the last `n` defined values. A
  leading run of na (an input that is itself warming up, such as script 9's
  `ta.ema(pulse, 20)` or script 5's `ta.sma(atr, 20)`) only delays the first
  value.
* **Window reset** — `Highest`, `Lowest`, `…Bars` and the pivots: a na input
  returns na (the `bars` forms return 0) and the window restarts after it.
  Warm-up is counted in bars, so after a leading run of na the extreme is
  taken over the shorter window since the na — and a pivot right after it
  can be confirmed with fewer than `leftbars` defined bars on its left.
* **Raw history** — `Change` and `History` keep na bars in their history.

**Ties.** `highestbars`/`lowestbars` report the *oldest* of equal extremes.
Pivots need `>=` against the left bars and strictly `>` against the right
bars (mirrored for lows), so of two equal highs the *newer* one is the pivot,
and of a flat top only its last bar. Pine re-reports a pivot when a
per-bar length changes; the Wyckoff port de-duplicates by pivot bar as the
script does.

**Comparisons.** Pine's comparison operators are tolerant: two floats whose
difference is at most 1e-10 are equal, so `a > b` is `a − b > 1e-10`, and
any comparison with na — `!=` included — is false. Strategy code that
reproduces a Pine expression uses `gt(close, ema200)` etc.; plain Python
operators are exact. The built-ins differ: `crossover`/`crossunder`,
`highest`/`lowest`, the pivots, `ta.sar` and `ta.supertrend` compare
exactly; `ta.dmi`'s directional-movement test and `ta.rsi`'s zero test use
the tolerance; `ta.cross` remembers the side `a` was last on by more than
1e-10 and fires when `a` is now strictly on the other side — so above →
equal → above is no cross (while `crossover` fires), and a series that
starts equal does not fire on its first separation.

## 14.4 SAR, SuperTrend and VWAP in detail

**`Sar`** follows `pine_sar` from the Pine reference manual:

1. Bar 0 is na.
2. Bar 1 initialises: `close > close[1]` starts long (SAR = `low[1]`, EP =
   `high`), otherwise short (SAR = `high[1]`, EP = `low`); af = `start`. The
   steps below then also run on bar 1, so bar 1 can already reverse.
3. Projection `sar + af × (EP − sar)` is tested **before** clamping: long
   reverses when it is strictly above `low`, short when strictly below
   `high`. On a reversal the SAR becomes `max(high, EP)` (`min(low, EP)`), EP
   the bar's low (high), af = `start`.
4. On other bars a new extreme moves EP and raises af by `inc`, capped at `max`.
5. The SAR is clamped: long ≤ `low[1]` and (from bar 2) `low[2]`; short ≥
   `high[1]`/`high[2]`.

TA-Lib and most libraries clamp before testing and flip on different bars.
`Sar.projected()` is the level whose touch flips the next bar — the trailing
stop of script 4's variant B (doc 13 D5) — and `is_long`, `extreme_point`,
`acceleration` expose the state.

**`SuperTrend`** follows `pine_supertrend`: bands `hl2 ± f × ATR`, the lower
band only rises (unless `close[1]` broke below it) and the upper only falls;
`nz(band[1])` is 0 on the first bar, so bar 0 returns `(0.0, 1)` and the line
is na until the ATR exists; the direction is forced to 1 while `atr[1]` is na;
then it is `close > upper ? −1 : 1` if the previous line was the upper band
(exact float equality) and `close < lower ? 1 : −1` otherwise. The flip
compares `close` with the **current** bar's ratcheted band. Jetstream's
BUY is `ta.change(direction) < 0`. `SuperTrend.atr` holds the bar's ATR for
"line ± 1 ATR" stops.

**`Vwap`** accumulates `Σ x·v`, `Σ v` and `Σ x²·v` from the last bar on which
`anchor` was true: `vwap = Σx·v / Σv`, `stdev = √max(0, Σx²·v / Σv − vwap²)`
(volume-weighted population deviation), bands `vwap ± m × stdev` for any `m`
(one object serves several `ta.vwap` calls with different multipliers). The
caller supplies the anchor: for the default `ta.vwap(hlc3)` that is the first
bar of each **trading day of the instrument** — the catalog's trading-day
rule (17:00 New York for CFDs, FX and metals, the CME session for futures,
00:00 UTC for crypto; doc 13 D8), not UTC midnight. Before the first anchor
the VWAP is na. Zero total volume is na (`0 / 0`), so a feed without volume
has no VWAP — script 9 then counts `close > vwap` as false on every bar; a na
volume makes the rest of the period na.

## 14.5 Where the received scripts use them

| Script | Calls | Classes |
|---|---|---|
| 1 BT+ICT | `ta.atr(14)` with `nz`, `ta.pivothigh/low(5,5)` and `(3,3)`, `ta.highest/lowest(26)[1]`, `ta.highestbars/lowestbars(26)[1]` | `Atr`, `nz`, `PivotHigh/Low`, `Highest/Lowest(+Bars)` + `History` for `[1]` |
| 2 ICT models | `ta.sma(body, 20)`, `ta.sma(vol, 20)`, `ta.atr(14)`, pivots (`mssLen`, 2/2 on 15m, `liqLen`) | `Sma`, `Atr`, `PivotHigh/Low` |
| 3 NQ toolkit | `ta.ema(9/21)`, pivots | `Ema`, `PivotHigh/Low` |
| 4 SMC suite | `ta.sar`, `ta.dmi(14,14)`, `ta.ema(7/21/200)`, `ta.pivothigh(volume,5,5)`, `ta.stdev(…,14)`, `ta.highestbars/lowestbars(…,15)`, `ta.highest/lowest(barssince)` (per-bar length), `ta.barssince`, `ta.vwap(hlc3, anchor, mult)` ×2, `ta.crossover/under` | `Sar`, `Dmi`, `Ema`, `PivotHigh`, `Stdev`, `HighestBars/LowestBars`, `Highest/Lowest(max_length=…)`, `BarsSince`, `Vwap`, `Crossover/Crossunder` |
| 5 Smart Money | `ta.atr(14)`, `ta.sma(atr,20)`, `ta.ema(50/100/200)`, `ta.rsi(14)`, `math.sum(…,20)`, pivots 40/40, 10/10, 10/3, 20/20, `ta.highest/lowest(20)[1]`, `ta.crossover(close, lsh)` before the update | `Atr`, `Sma`, `Ema`, `Rsi`, `Sum`, `PivotHigh/Low`, `Highest/Lowest` + `History`, `Crossover` (history as passed) |
| 6 Wyckoff | `ta.atr`, `ta.sma`, `ta.cum(volume)`, `ta.highest/lowest` (many), `math.sum`, pivots with a **per-bar** length (2…10), `math.round` (ties) | `Atr`, `Sma`, `Cum`, `Highest/Lowest`, `Sum`, `PivotHigh/Low(max_left=10, max_right=10)`, `pine_round` |
| 7 Order Flow Desk | `ta.sma`, `ta.atr` with `nz`, pivots, `ta.cross`, `ta.change(math.sign(delta))`, own VWAP with weight 1 for zero volume | `Sma`, `Atr`, `PivotHigh/Low`, `Cross`, `Change`; `Vwap` with the script's weight passed as volume |
| 8 FRVP + ORB | `ta.ema(9/20)`, `ta.crossover/under`, `math.round_to_mintick` | `Ema`, `Crossover/Crossunder`, `round_to_mintick` |
| 9 EliteAlgo | `ta.ema(8/21/200)`, `ta.rsi(14)`, `ta.atr(14)`, `ta.dmi(14,14)`, `ta.vwap(hlc3)`, pulse EMA5−EMA60 and its EMA20, `ta.sma(atrPct,100)`, `ta.crossover/under` | `Ema`, `Rsi`, `Atr`, `Dmi`, `Vwap`, `Macd(5,60,20)`, `Sma`, `Crossover/Crossunder` |
| 10 Jetstream | `ta.supertrend(3,10)`, `ta.change(dir)`, WaveTrend (`ta.ema`, `ta.sma`), `ta.macd(12,26,9)`, pivots 10/10 and on `wt2` 5/5 | `SuperTrend`, `Change`, `WaveTrend`, `Macd`, `PivotHigh/Low` |

## 14.6 Evidence, and what is still unverified

Two sources define the behaviour above:

* **TradingView's Pine reference manual** — the documented semantics and the
  reference implementations it prints (`pine_sma`, `pine_ema`, `pine_rma`,
  `pine_atr`, `pine_rsi`, `pine_dmi`, `pine_sar`, `pine_supertrend`,
  `ta.vwap`'s band formula). `Dmi`, `Sar` and `SuperTrend` transcribe them.
* **Behaviour the PyneCore project reports having measured** against
  TradingView output (an open-source Pine runtime, Apache-2.0; its source
  comments describe each probe). We read it as reference material only; no
  code was copied. It is the source for: na-compacted averages; the na
  reset, warm-up and tie rules of `highest`/`lowest`/pivots; EMA/RMA step
  forms; the one-pass variance; `crossover`/`crossunder` skipping na bars;
  `ta.cross`'s remembered side; RSI's 1e-10 zero test; DMI's tolerant DM
  comparison; `math.round` ties away from zero and the 1e-10 near-tie rule;
  the 1e-10 comparison tolerance.

**None of it has been checked against our own TradingView exports yet**:
TradingView is not reachable from the development environment and no chart
exports have been provided. Until the parity checks below pass, these points
are assumptions:

| Point | Implemented | Alternative to rule out |
|---|---|---|
| Pivot ties | `>=` left, `>` right (newer of equal highs) | strict both sides / older one |
| `highestbars`/`lowestbars` ties | oldest bar | newest bar |
| na inside a pivot or `highest` window | window reset | PyneCore: a pivot skips the window update on a na bar instead (old values stay) |
| `ta.sar` start | `pine_sar`: `close > close[1]` on bar 1, reversal test on bar 1 | PyneCore: `high[1] > high`, no test on bar 1 (only the path before the first reversal differs) |
| `ta.dmi` with a zero true-range average | `fixnan` keeps the previous DI (`pine_dmi`) | PyneCore: na for all three |
| `ta.vwap` before the first anchor | na | starts on the chart's first bar |
| `ta.vwap` default anchor | caller passes the instrument's trading-day start | TradingView's per-symbol session may differ (doc 13 D8) |
| na inputs to SAR, SuperTrend, RSI | bar skipped / TR na rules | — (no received script feeds na OHLC) |
| `math.round(x, p)` near-ties and `round_to_mintick` | exact fraction with the 1e-10 band | double arithmetic |
| ta.cross on equality plateaus | remembered side | `crossover or crossunder` |

## 14.7 Checking against TradingView

1. Put the indicator (or a harness script that `plot()`s the built-in) on a
   TradingView chart of the instrument and timeframe; *Export chart data*
   writes the bars and every plot as CSV columns.
2. Feed the exported OHLCV through the class with `feed(...)` and compare the
   column, skipping the warm-up: EMA/RMA-based values converge from their
   seed, so compare only after several times the length (≥ 1000 bars for
   EMA200, ATR/RSI/DMI); SAR and SuperTrend only after their first reversal
   (their path depends on where history starts).
3. Expect agreement to ~1e-9 relative on smoothed values and exact equality
   on extremes, pivots, crosses and directions. Any mismatch on a tie, an
   equality or the first bars resolves a row of the table in 14.6.

## 14.8 Tests and versions

`tests/unit/indicators` holds hand-computed vectors for every class, property
tests (Hypothesis) against whole-array reference implementations written
from the definitions above (windows sliced, EMAs in closed form, the Pine
reference functions transcribed with `x[k]` look-ups), edge cases (na at the
start and in the middle, length 1, constant series, equal highs/lows,
per-bar lengths, long runs) and determinism. Branch coverage of the package
is 100 %. Every class costs a few microseconds per bar.

The indicator source is part of `framework_fingerprint()`, recorded with
every strategy version for audit. Doc 13 P3 asks that an indicator fix also
create a new strategy version; that needs the indicator source hash in the
instance `config_hash` (strategy engine, not done here).

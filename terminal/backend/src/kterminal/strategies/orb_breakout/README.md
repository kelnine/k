# orb_breakout — opening range breakout with the EMA 9/20 filter (S2)

Port of `terminal/pine/received/08_frvp_orb_ema.pine` ("FRVP + ORB + 9/20
EMA"), spec `terminal/pine/specs/08_frvp_orb_ema.md`, doc 13 strategy **S2**
(the London ORB is its D11 variant). The script is an indicator: it draws the
opening range, a marker and an alert on the breakout bar, and defines no stop,
target or exit. Line numbers below are the received file's. The volume profile
(L166-305) and the EMA-cross alerts (L163-164) are display/alert only and are
not ported (doc 13 D12).

## Rules

| Rule | Pine | Port |
|---|---|---|
| EMAs | L100-103: `emaFast = ta.ema(close, 9)`, `emaSlow = ta.ema(close, 20)`, `bull = emaFast > emaSlow`, `bear = emaFast < emaSlow` | `Ema(9)`, `Ema(20)` updated on every bar; `gt`/`lt` (Pine's 1e-10 tolerance, false while an EMA is na) |
| Windows | L113-114: `inOR`/`inLvls = not na(time(timeframe.period, sess, tz))`, `orSess` 0930-0945, `lvlSess` 0930-1600, `tz` America/New_York | `ctx.in_session(param, timezone)`: by the bar's **open** time, half-open `[start, end)`, DST-correct, every day (the strings have no day mask, Pine v5+ default) |
| Range start | L115, L121-126: `orStart = inOR and not inOR[1]` creates a new `ORDay` at the bar's high/low with both counters unused | Same; `inOR[1]` is the previous primary bar's `inOR` (false before the first bar). The new range replaces the old one at once, so no signal fires on OR bars |
| Range build | L127-132: later bars inside the window widen it to their **wick** high/low | Same |
| Range formed | L116, L134-136: `orEnd = not inOR and inOR[1]` sets `formed` on the first bar after the window | Same; that bar can already signal (09:45 on 5m) |
| Long | L143, L150-153: range formed, bar opens inside `lvlSess`, `not longDone and close > cur.hi and (not orFilter or bull)` | Same, on the closed bar (`barstate.isconfirmed` is always true for closed bars). A **state**, not a cross: a long blocked by the EMA filter fires later on the first bar where the EMAs agree while the close is still above the range |
| Short | L154-156: `close < cur.lo and (not orFilter or bear)`, `shortDone` | Same |
| Once per day | L151-156: `longDone`/`shortDone` are set exactly when the marker is drawn; a new `ORDay` resets them | Same: the counter is used up whenever the script would draw the marker — also when the trade is then skipped (D5 late signal, D3 gap guard) or ignored (D4), and on warm-up bars |
| Stale range | L120-156: `cur` is replaced only by `orStart` | A day without a bar opening in the OR window keeps the previous range and its unused signals during that day's levels window (`metadata.stale_range`) |

Each entry carries in `metadata`: `pine_signal` (`orLong` / `orShort`),
`trigger` (`ORB long` / `ORB short`, the script's marker and alert title),
`close`, `or_high`, `or_low`, `or_mid` (`math.avg`, L135), `or_start` (open
time of the bar that started the range), `stale_range`, `ema_fast`,
`ema_slow` (null while na), `or_filter`, `stop_mode`, `target_r`, `flatten_at`
(the trade's flatten instant) and `bar_index`. Flatten exits carry `exit:
flatten`, `flatten_time` and `flatten_at`.

## Params

| Param | Pine input | Default |
|---|---|---|
| `timezone` | `tz` (L9) | `America/New_York` |
| `or_session` | `orSess`, "Opening range" (L30) | `0930-0945` |
| `levels_session` | `lvlSess`, "Levels active during" (L31) | `0930-1600` |
| `or_filter` | `orFilter`, "Only in the direction of the EMAs" (L34) | true |
| `fast_length`, `slow_length` | `fastLen`, `slowLen` (L38, L40) | 9, 20 |
| `stop_mode` | — (D5) | `range`: the other side of the range; `midpoint`: the range midpoint |
| `target_r` | — (D5) | 2; `null` = no target (flat at `flatten_time` only); > 0, ≤ 100 |
| `flatten_time` | — (D5) | `16:00` local in `timezone`; `HH:MM`, validated |

Session strings are validated and normalised (`0930-0945` →
`0930-0945:1234567`), so equal windows give equal versions. `showOR` and
`orSignals` are not params: either one off disables every signal (L120,
L150). Colours, `orKeep` (drawings kept) and the profile inputs do not change
signals.

## Variants and instances (`config/instances.d/orb_breakout.yaml`)

| Instance | Instruments | Range / levels / flatten | Stop | Target |
|---|---|---|---|---|
| `orb_breakout_ny_5m` | MNQ, NAS100, US30, US500 | 09:30-09:45 / 09:30-16:00 / 16:00 New York | other side of the range | 2R |
| `orb_breakout_ny_mid1r_5m` | same | same | midpoint | 1R |
| `orb_breakout_ny_mid1p5r_5m` | same | same | midpoint | 1.5R |
| `orb_breakout_ny_mideod_5m` | same | same | midpoint | none: closed at 16:00 |
| `orb_breakout_london_5m` | XAUUSD, EURUSD, GBPUSD, NAS100, US30, US500 | 08:00-08:15 / 08:00-16:30 / 16:30 London | other side of the range | 2R |

All on 5m (D10), script defaults for the signal inputs (D13), one Paper 50K
account per instance with `max_open_positions` equal to its number of
instruments (one position per instrument).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| Entries fill at the **next bar's open**; stop and target stay at the levels computed from the signal close | The lab's fill model (doc 01 §1.7, doc 13 D3); the user compares against the marker on the signal bar |
| Stop at the other side of the opening range (`range`) or its midpoint (`midpoint`); target `target_r` × \|close − stop\| from the signal close. Both exact in decimal, rounded to the tick, ties away from zero | Doc 13 D5: the script defines no stop or target; the lab needs a stop to size the trade |
| A trade is closed with exit reason `SESSION_CLOSE` at the open of the first bar at or after `flatten_time` of the day it was **signalled**: the exit is decided on the bar whose close reaches that time (15:55 on 5m, filled at 16:00). A fill that a data gap delayed past that time is closed at once | Doc 13 D5 "flat by 16:00 (16:30 London)" |
| A signal whose next-open fill would land at or after `flatten_time` (the bar closing at 16:00) is not traded: a persisted `NO_TRADE` with reason `FILL_AT_OR_AFTER_FLATTEN` and the script's metadata. Its counter is used up | Doc 13 D5 / spec: "skip signals whose fill would land at or after 16:00" |
| An entry whose fill bar opens at or beyond its stop or target is skipped (`ORDER_CANCELLED`, `OPEN_BEYOND_STOP` / `OPEN_BEYOND_TARGET`; meta `skip_entry_beyond_levels`) | Doc 13 D3 |
| A stop or target that is not beyond the rounded entry is not traded (`STOP_WRONG_SIDE` / `TARGET_WRONG_SIDE`) | Doc 13 D3. Cannot happen with these stops (the close is strictly beyond the range) and a target_r > 0 on a one-tick risk; kept as a guard |
| An opposite signal while in a trade is ignored (meta `on_opposite_signal: ignore`); a same-direction signal is ignored too (one position per instrument) | Doc 13 D4 for script 8. With either stop the opposite breakout can only close beyond the stop, so the trade is already stopped out when it is decided: the policy never changes a trade in the book (tested). An account filling at bid/ask can still hold a trade the book closed |

## Parity notes

* **Marker vs fill.** TradingView prices the breakout at the signal bar's
  close; the lab fills at the next open.
* **Sessions by bar open.** The chart timeframe must be 15m or smaller and
  aligned to 09:30 (08:00 London) for a 15-minute range; `meta.timeframes` is
  1m, 5m, 15m. On 15m the range is the single 09:30 bar.
* **Every day.** The sessions have no day mask, so a weekend with bars forms a
  range like the script; none of the configured instruments trades at 09:30
  New York or 08:00 London on weekends.
* **Gaps.** Two bars in different occurrences of the OR window (a data gap
  across the closed hours) are not a new start, exactly like `inOR[1]`; a day
  with no OR bar carries the previous range over (L120-156). Both are tested.
* **Feeds.** The user's TradingView feed (NAS100 CFD vs MNQ1!) has different
  09:30-09:45 extremes from ours; one tick changes which bar breaks out.
* **EMA warm-up.** The EMAs depend on the overnight bars present (24h CFDs and
  futures, as on the user's chart); `warmup_bars` covers EMA20 convergence.
* **UK vs US clocks.** The London variant follows the UK clock (tested in the
  weeks when the US has already changed and the UK has not).
* **Not checked against TradingView**: TradingView is not reachable from the
  development environment and no exports were provided. Correctness is shown
  by golden scenarios and by an independent transcription of L100-156 run
  against the port on synthetic data (`tests/unit/strategies/orb_breakout`).

## Warm-up

`meta.warmup_bars = 300`: EMA20 converges (its seed weighs < 1e-12 after 300
bars) and on 5m the warm-up reaches back about 25 hours, so the current or
the previous opening range is always seen. The forward runtime's default
`forward.warmup_days: 10` covers it.

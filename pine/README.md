# Pine scripts

## `combined-smc-suite.pine`

Three overlays merged into a single TradingView indicator, each behind its own
on/off switch in a **Modules** group at the top of the settings:

| Toggle | Module | Source |
| --- | --- | --- |
| Order Block Detector | Volume-pivot order blocks, average line, mitigation by wick or close | LuxAlgo (CC BY-NC-SA 4.0) |
| Smart Money Breakout Channels | Volatility-compression channels, breakout signals, in-channel volume/delta bars, side gauge | AlgoAlpha (MPL 2.0) |
| 200 EMA Filtered Parabolic SAR | PSAR flips filtered by a 200 EMA trend regime and an ADX threshold, with Long/Short entries and EL/ES exits | reconstructed |

Every original input is preserved with its original default, namespaced per
module (`ob*`, `bc*`, `ps*`) so nothing collides. Alerts from all three are kept,
plus two confluence alerts (PSAR entry in the same direction as a channel
breakout).

### Notes on the merge

- The scripts were `//@version=5` (LuxAlgo) and `//@version=6` (AlgoAlpha); the
  combined file is v6.
- Order-block mitigation now walks its arrays back-to-front. The original walked
  forward while removing elements from the array it was iterating, which skips
  entries and can read past the end.
- The channel loop was changed the same way, for the same reason.
- v6 dropped implicit float→bool conversion. `ta.pivothigh()` returns a price
  rather than a flag, so the order-block trigger is now `not na(...)`, and the OB
  "formed" alerts test the price series the same way instead of passing a float
  straight to `alertcondition`.
- The channel-formation `ta.crossover()` calls are hoisted to their own variables.
  Behind a short-circuiting `and` they would not run on every bar, which corrupts
  the history those functions depend on (CW10002).
- The library is imported as `tvta`, so `tvta.requestUpAndDownVolume()` is
  unambiguous and every other `ta.*` call resolves to the built-in namespace.
- Shorttitle is `SMC Suite` — TradingView caps it at 10 characters.
- Order-block boxes and average lines are allocated on the **last** bar rather than
  the first. TradingView evicts the oldest drawings once `max_boxes_count` /
  `max_lines_count` is reached, and the channel module creates four drawings per
  channel over the whole history. Built at bar 1 the order blocks were first in line
  for eviction and disappeared silently. Standalone, LuxAlgo never hits the cap
  because it only holds six boxes; sharing one budget with the channel module, it
  does. The trade is that the oldest off-screen channel boxes are now the ones
  evicted instead.
- Disabling a module skips its drawing objects entirely rather than hiding them,
  so an unused module costs nothing against the 500-box / 500-line limits.
  `ta.requestUpAndDownVolume()` is the one exception — `request.*` calls must stay
  unconditional, so it is evaluated even with the channel module off.

### About the Parabolic SAR module

Only screenshots of that indicator's settings were available, not its source, so
it is a reconstruction from the visible inputs (`MaFastLength` 7, `MaMedLength`
21, `MaSlowLength` 200, `PSARstart` 0.02, `Increment` 0.02, `Maximum` 0.2, ADX
Smoothing 14, DI Length 14, Threshold 20, "Show the 21 EMA?") and the visible
plot list (SAR long/short shapes, exit long/short shapes, three MA plots, the SAR
plot, and a background). Two behaviours were inferred and may not match the
original:

- **Entries** fire on a SAR flip that agrees with the 200 EMA and clears the ADX
  threshold; **exits** fire on the opposite SAR flip while a position is open.
- **Plots Background** is a `fill()` band between the fast and medium MA (Color 0
  while the fast MA leads, Color 1 otherwise). In the Style tab a `fill()` between
  two plots is what shows up as "Plots Background" with Color 0 / Color 1 — it is
  not a `bgcolor()`, which would wash out the whole chart and hide the order-block
  bands behind it.

Send the original source if those need to match exactly.

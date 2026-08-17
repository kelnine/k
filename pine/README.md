# Pine Script

TradingView indicators that mirror the concepts KCharts renders natively.

## `phantom-flow-sessions.pine`

**Phantom Flow — Sessions, Zones & Gaps** (`//@version=6`). Paste the file into
TradingView → *Pine Editor* → **Add to chart**. Works on any symbol; defaults are
tuned for index futures on a 5–15 m chart.

### What it draws

| Feature | Detail |
| --- | --- |
| **Session ranges** | Asia, London, NY AM, NY Lunch, NY PM. Shaded box while the session runs; high/low lines + `ASIA HIGH` / `LONDON LOW` style labels that keep extending to the right of price. |
| **Sweeps** | When price trades back through a closed session's high or low, that line flips to dotted and an alert fires. |
| **PD / PW / PM** | Previous day, week and month high & low, anchored at the start of the current period. |
| **Fair value gaps** | Three-bar gaps on the chart timeframe plus a second set from a higher timeframe (default 1 H). Boxes extend until mitigated — mitigation rule is `Touch`, `50%`, or `Full fill`. |
| **Buy / sell zones** | Premium & discount OTE bands (default 0.62–0.79) off the live dealing range between the last confirmed swing high and low, with a 50 % equilibrium line. |
| **ORB** | Opening-range box for a configurable window (default 09:30–09:45 NY), extended high/low lines, and `ORB ▲` / `ORB ▼` breakout markers graded by runway (below). Markers sit on the breakout bar itself. |
| **Gap fill** | Box spanning the prior day's close to today's open; it greys out and alerts the moment price trades back through the old close. |
| **Range table** | Per-session range with that range as a % of its own trailing average, plus PD / PW / PM rows. Green ≥ 100 %, amber ≥ 75 %. |

### ORB breakout runway filter

A break only gets a solid marker when it has somewhere to go. On the bar that
first closes beyond the opening range, the script measures:

1. **Target** — the nearest level in the break's direction that price is plausibly
   drawn to: an **unswept** session high/low, PDH/PDL, or an unfilled overnight
   gap. Only sessions that have *closed* count, since a session still in progress
   has its high and low pinned to current price. Levels you have switched off are
   not considered.
2. **Runway** — the target must be at least *Minimum runway* ATR(14) multiples away
   (default 1.0×). This is applied while searching, so a level sitting right on top
   of price can't mask a good target behind it.
3. **Obstacles** — how many live, unmitigated FVGs sit between the break and the
   target. Must be ≤ *Max unfilled FVGs in path* (default 3 — index futures on
   fast timeframes print FVGs constantly, so 1 rejects almost everything).

Pass both and you get a solid `ORB ▲` / `ORB ▼` plus an alert. Fail either and the
marker prints grey with a `?` and **no alert fires** — that is the "broke into a
wall of imbalance" case. Hover any marker for the target name, the runway in ATR,
and the obstacle count that produced the verdict.

A break with no unswept target ahead of it is treated as filtered. Turn the whole
test off with *Filter breakouts by runway* to get raw breaks back.

Note that both directions can still fire on the same day — the range genuinely
broke twice. The filter grades each break, it does not predict which one holds.

### Settings that matter most

- **Timezone** — every session string is evaluated in this zone. `America/New_York`
  by default, so `0930-1200` really is the NY morning regardless of chart timezone.
- **Session strings** — standard Pine session format, overnight windows included
  (`1800-0000` for Asia). Append `:23456` to restrict to weekdays.
- **Keep previous days' drawings** — off by default so only the most recent
  instance of each session stays on the chart.
- **Extend levels (bars)** — how far past the last bar the levels and labels run.
- **Mitigate on** — how aggressively FVGs are retired. `Touch` clears them as soon
  as price grazes the near edge; `Full fill` waits for a complete rebalance.
- **Swing length** — the pivot lookback that defines the dealing range the buy and
  sell zones are measured from. Larger = fewer, bigger ranges.

### Alerts

Create one alert on the indicator with **Any alert() function call**; the message
tells you which event fired:

- `<SESSION> HIGH/LOW swept at <price>`
- `Price tapped the BUY/SELL zone (<low> – <high>)`
- `ORB breakout up/down through <price>`
- `Overnight gap filled at <price>`

### Notes

- Chart-timeframe FVGs are only committed on confirmed bars, so nothing on a
  closed bar repaints. Higher-timeframe FVGs are evaluated once per new HTF bar
  using closed HTF values (`lookahead_off`).
- HTF FVGs are skipped automatically when the selected timeframe is lower than the
  chart's.
- Every drawing is created once per instance and then updated in place, which
  keeps the script inside TradingView's 500-box / 500-line / 500-label budget.

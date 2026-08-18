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
| **ORB** | The first candle of the NY session: its **open** (dotted), high and low (dashed), all extended. `ORB ▲` / `ORB ▼` breakout markers and `ORB REJ` rejection markers, graded by runway, sweep and volume (below). Markers sit on the signal bar itself. |
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

### Volume confirmation

*Require volume confirmation* adds a second gate on every ORB signal: the signal
bar's volume must be at least *× average* (default 1.5×) of the trailing average
(default 20 bars). It applies independently of the runway filter, so you can run
either, both, or neither. Symbols with no volume feed pass automatically rather
than blocking every signal.

Off by default — it stacks on top of the runway test, so switch it on once you
know how the runway test alone behaves on your instrument. Every marker tooltip
reports the bar's volume as a multiple of average whether the gate is on or not,
which is the cheap way to find the right threshold before enabling it.

### ORB rejections

The other side of the same level: the edge holds instead of giving way, and the
fade is the trade. Two definitions, selectable under *Rejection signal*:

- **Wick** — the bar trades through the edge and closes back inside the range.
- **Failed break** — a break already confirmed (closed outside) gets reclaimed by
  a later close back inside.

`ORB REJ ▼` is a top-side rejection (a short), `ORB REJ ▲` a bottom-side one (a
long). Same greyed-with-`?` treatment when it fails the test, same tooltip.

**Target.** A refused break aims at the *other side of the opening range* — a
top-side rejection targets the ORB low. That is the default. Switch *Rejection
target* to `Nearest liquidity` to grade rejections the same way breakouts are,
against the next unswept pool instead.

**Sweep.** The strength of a rejection is usually in what the failed probe took
out on its way — a previous day high, a session high. The tooltip always reports
this as *Swept on the probe*, listing every level caught between the ORB edge and
the furthest point the probe reached. Turn on *Rejection requires a liquidity
sweep* to only confirm rejections that swept something.

Rejections fire at most once per side per day and are independent of the breakout
markers, so a break followed by a reclaim gives you both: `ORB ▲` then
`ORB REJ ▼`.

### Bias

The table's **BIAS** row tracks the running read the opening range gives you:
holding above the range is `LONG`, refused and back inside is `SHORT`, and it
flips as breaks and rejections fire. The third column shows the range itself
(high / low). It is a state read-out, not a signal — the markers are the signals.

### Fib pullback filter on FVGs

Marking every gap buries the few worth watching. *Only gaps in the fib pullback
zone* hides any FVG that isn't sitting in the retracement band of the current
dealing range — by default 0.5–0.62, measured from both ends of the range so it
catches a pullback in either direction.

The band moves as the dealing range does, so a gap can drift into and out of it
over its lifetime; the filter is re-evaluated every bar rather than fixed at
detection. Hidden gaps are still tracked — mitigation and the breakout
obstacle count use every gap, visible or not.

### Keeping the chart readable

With every session, PD/PW/PM level and FVG labelled at once, the right-hand edge
turns into a stack of overlapping text. Two controls under **Labels & clutter**:

- **Label FVG boxes** — off by default. The coloured box already identifies itself,
  and one label per gap is most of the noise.
- **Only label levels near price** with **Label distance (× ATR)** (default 3×) —
  session and PD/PW/PM levels further away than that draw as bare lines. The line
  never moves; only its text hides, and it comes back as price approaches.

Neither affects detection — sweeps, targets and the runway filter all still use
every level, labelled or not.

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

---

## `deliverance-multi-session-orb-v2.pine`

**Deliverance Multi-Session ORB v2** (`//@version=6`). Standalone — it neither
reads nor modifies the other scripts here.

v1.0 is carried forward **intact**, not reimplemented: `f_cisd()` is byte-for-byte
identical, and the CISD delivery legs and zones, SH/SL structure rays, swing
signals, SMT divergence and the HTF/MTF CISD + open bias rows all keep v1's
behaviour, inputs and palette. Four independent 15-minute opening ranges are
layered on top.

| Session | Default window (ET) | Label |
| --- | --- | --- |
| Globex open | 18:00–18:15 | `GLOBEX ORB` |
| London open | 03:00–03:15 | `LONDON ORB` |
| New York cash open | 09:30–09:45 | `NY ORB` |
| PM range | 13:45–14:00 | `PM RANGE` |

Every window is editable and every session has its own toggle. Windows resolve in
`America/New_York`, so DST comes from TradingView's session engine.

### The progression

A basic break is not a signal. Each session walks its own state machine, and no
session reads or writes another's state:

```
range forms → break → close outside → retest → CISD confirmation → entry
```

| Status | Meaning | Marker |
| --- | --- | --- |
| Waiting | Range fixed, untouched | — |
| Early Break | Traded through an edge, no close outside | `EARLY ▲/▼` |
| Confirmed | Closed outside the range | `NY ORB ▲` |
| Retest | Returned to the broken level and held it | `ORB RETEST` |
| Conf Long / Conf Short | Every enabled requirement met | `CONF LONG` / `CONF SHORT` |
| Re-armed | A refused break flipped the session onto the other edge | — |
| Failed | Refused a second time; done for the day | `ORB REJ` |

Requirements are individually switchable: *close outside range*, *retest*,
*CISD/structure confirmation*, *agreeing SMT*. Confirmation reuses v1 directly —
it fires when `cisdState` or `swingTrend` already reads in the break's direction.

**Failure is buffered, and it re-arms.** A one-tick reclaim of the broken level
is noise, not a failed breakout — on fast timeframes price crosses back over a
level constantly, which kills nearly every break before it can develop. So a
failure needs the close to get back inside by *Failure buffer* (default 0.15 of
the range), optionally for several consecutive closes.

When a break does fail, the session does not end its day. With *Failed break
re-arms the opposite side* on (the default) it flips to hunting the other edge —
a refused push through the high turns the session into a short looking for the
low, which is how the setup is actually traded. One re-arm per session per day,
so it cannot ping-pong.

### Bias

Straight from v1: HTF and MTF bias are the **CISD state** of those timeframes via
`f_cisd()`, alongside v1's open bias row. Both agreeing gives **Strong Long** or
**Strong Short**; disagreement is **Mixed**.

Bias *grades* a setup by default — every confirmation is tagged Strong, Mixed or
Counter in its tooltip and alert, and nothing is blocked. The two filter inputs
turn it into a hard gate if you want one.

### Statistics

Per session, **never pooled** — the point is comparing Globex vs London vs NY vs
PM on the same instrument.

Setups, wins, losses, win rate, bullish breaks, bearish breaks, failed breaks. A
virtual trade opens at each confirmation and resolves when price reaches the stop
or the target. **A bar spanning both counts as a loss** — bar data cannot say
which came first. Stop placement (opposite range side / retest swing / ATR) and
the R multiple that counts as a win are inputs, so nothing is invented.

Statistics accumulate from whatever history the chart holds and reset on reload.
On a 5m chart that is a few months — a small sample for comparing four sessions,
so treat early win rates as noise.

### Notes

- **Use a 5m or 15m chart.** The window is 15 minutes wide; the dashboard shows a
  warning row above 15m.
- All progression logic runs on `barstate.isconfirmed`, and both bias reads come
  from closed higher-timeframe bars, so nothing repaints.
- **Clean mode** declutters the chart — range names, early-break and retest
  markers and the range open — leaving boxes and confirmed signals. It does not
  touch the corner panels: the dashboard and statistics table have their own
  toggles. While testing, turn clean mode off so you can see whether breaks are
  reaching the retest stage.
- Historical ranges are off by default; when on, old drawings are archived and
  recycled past *Days of history to keep*.
- An indicator, not a strategy. It marks setups and keeps score; it places no orders.

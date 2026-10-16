# wyckoff_auto — Wyckoff campaign engine, Auto entry (S12)

Port of `terminal/pine/received/06_wyckoff_theultimator5.pine` ("Wyckoff
[theUltimator5]", Pine v6, 3,199 lines), spec
`terminal/pine/specs/06_wyckoff_theultimator5.md`, doc 13 strategy **S12**. The
script is an indicator: it runs a Wyckoff campaign state machine (`f_engine`,
L1060-1764), draws the schematic, and stamps an Auto entry per campaign for
the chosen Entry Strictness, with alerts "Wyckoff: long entry" / "Wyckoff:
short entry" (L3198-3199). It has no stop, no target and no position. Line
numbers below are the received file's.

| Module | Pine |
|---|---|
| `thresholds.py` | the ~106 fixed settings (L53-176), one constant per Pine name; thresholds the script writes inline (`sprATR >= 0.80`, `pEff <= climaxEff * 1.20` …) stay inline in the code next to their line number |
| `state.py` | the `WS` campaign type (L366-483) field by field, `PivotTriplet` (L354-363), the integer codes (L178-263) |
| `measures.py` | the per-bar series of `f_engine` (L1062-1159): effort, ATR, the adaptive swing length, the pivots and their back-dated snapshot, the prior-trend score (`f_priorTrendScore`, L573-613), the windows of closes, the SOS/SOW scores — one `kterminal.indicators` object per Pine call site, updated on every bar |
| `wyckoff_engine.py` | the helpers (L614-974) and the commit block of `f_engine` (L1162-1747), statement by statement in the script's order |
| `strategy.py` | the signals: the Auto entry with the D5 stop, the structure exits |

Only the chart-timeframe engine and its Auto entry are ported. The
higher-timeframe override (L1766-2008, on by default), the reference-label
entry modes, the historical schematics, the status tables and every drawing are
not (see the deviations).

## Rules

`f_engine(barstate.isconfirmed)` commits on closed bars (L1795); the lab
delivers closed bars only, so every bar commits. Each closed bar runs, in the
script's order:

| Step | Pine | What happens |
|---|---|---|
| Measures | L1062-1159 | `eff` = volume, or the bar range while the cumulative volume is still 0 (all or nothing, L1064-1066); `avgEff` = SMA 50 of `eff`; `a` = `nz(ATR(14), range)`; `pLen` = the campaign's frozen length, or the live length `clamp(round(4 × ATR / SMA(ATR, 50)), 2, 10)` when idle (L1085-1088, L1105); `ta.pivothigh/low(pLen, pLen)` with that per-bar length and the pivot bar's ATR, effort, spread, close position and time read `pLen` bars back (L1106-1114); the prior-trend score -100…+100 over 25-80 bars ending 2-8 bars ago (L1116-1122); SMA 200 context (L1123-1124); PS efficiency (L1126-1134); highest/lowest closes over 2, 3 and 5 bars; the multi-bar SOS/SOW (L1148-1152); the SOS/SOW scores (L1155-1156) |
| Retire | L1164-1234 | Phase A: two closes 0.5 ATR beyond the climax (RS_INVALID), no absorption within 8 bars (RS_ABSORB), no 2-ATR AR within 30 bars, an AR over 15 climax ATRs, or a departure from the range after 30 bars (RS_NORANGE). Phase C (no open probe) and D: two closes 0.5 ATR beyond the hard level (RS_INVALID). Phase D: three closes past the range middle → **demotion to Phase B** (the campaign survives). Phase E: three closes past the middle or more than 300 bars (RS_EEND). Phases A-D: no activity for the phase's idle limit (RS_STALE: A 30/45, B 125, C 50, D 100 bars at `pLen` 4) |
| Climax | L1236-1275 | preliminary support/supply tracked while idle or in Phase E (L1237-1252); a selling climax = downtrend (score ≤ -15), a new 30-bar low, effort ≥ 1.8 × the previous average, range ≥ 1.5 × the previous ATR (both × 0.8 in a strong trend), score ≥ 5 of 6 (L1254-1264); a new climax replaces an idle or Phase E campaign, or a Phase A one it extends; it **seeds Phase A** with `pivLen = liveLen[3]` (L1271) |
| Phase A | L1277-1311 | absorption 3-8 bars after the climax confirms it (L1278-1290, the SC/BC event); the AR runs on the highs (lows) for 30 bars and becomes the range's far edge once absorbed and 2 ATR away (L1292-1311) |
| Pivots | L1313-1475 | in a mature Phase B a quiet pivot near the climax edge is the **terminal C-Test** → Phase C with an outcome (L1328-1369); in Phase A the first good test of the climax edge fixes the AR and starts **Phase B** at the pivot bar (L1371-1410); in Phase B, tests of the climax edge are STs (the edge becomes the median of the last three, never beyond the original, L690-698, L775-807) or bad tests; tests of the opposite edge are opposite tests and may widen it by 15 % (L1413-1462); zone changes count traversals (L1465-1475) |
| Test, LPS | L1477-1529 | after a Spring/UTAD, a quiet pivot within 1.25 ATR of the edge holding the Spring is its **Test** (L1477-1502); in Phase D a quiet pivot above the creek − 1.5 ATR and above the hard level is the **LPS/LPSY** (L1504-1529) |
| Probes | L1531-1610 | a 0.15-2.5 ATR penetration of the range edge opens a pending probe (Phase B after 2 × `pLen` bars with an ST, or Phase C without a Spring); recovering within `max(3, round(0.75 pLen))` bars with 3 of 4 points makes it a **Spring/UTAD** (Phase C, outcome set, L1587-1591) — or, while Phase B is not mature, a provisional one (L1576-1586); too deep or too slow drops it (cool-down `pLen` bars). Before its Test the Spring deepens with lower lows (L1598-1610) |
| SOS/SOW | L1612-1641 | in Phase C, `max(3, pLen/2)` bars after the Test (or Spring) and with validation ≥ 60 and confidence ≥ 45 (+13 / +30 without a Test): a close beyond the range + 0.15 ATR, or two (three) closes beyond 65 % of it, with a strength score ≥ 3, the multi-bar SOS or a 3-bar 1-ATR move → **Phase D** (L1623-1641) |
| Departure | L1643-1676 | in Phase B a sustained exit from the range adopts a provisional Spring/UTAD and promotes straight to Phase D (Spring + SOS, L1654-1669) — without one, three closes beyond the edge + buffer retire the campaign (RS_DEPART) |
| Re-SOS | L1678-1693 | after an LPS (LPSY) a wide, high-effort close beyond the range is a renewed SOS (SOW) |
| Phase E | L1695-1727 | three closes beyond the range after the LPS (or five, with confidence ≥ 75, without one) → **Phase E**; sets the markup/markdown regime that delays the next opposite campaign's promotion by 25 bars (L1175-1176) |
| Auto entry | L1729-1747 | once per campaign (`na(s.entryTime)`), when it has an outcome: the trigger of the Entry Strictness on this bar, if confidence, validation and readiness pass (below) |

`f_hardLevel` (L723-729) — the stop's basis — is the Spring/UTAD extreme when
the campaign has one for its outcome, else the more extreme of the original
edge and the current range edge (for a climax-origin campaign, the climax
itself).

### The Auto entry (L1729-1747)

| Strictness | Triggers | Confidence | Validation | Readiness (of 9) |
|---|---|---|---|---|
| Conservative | `conservativeLpsTrig`: an LPS/LPSY on this bar | ≥ 75 | ≥ 60 | ≥ 7 |
| Standard (default) | `standardTestTrig`: a Spring/UTAD Test or a C-Test on this bar; `standardLpsFallback`: an LPS/LPSY on this bar | ≥ 60 | ≥ 50 | ≥ 6 |
| Aggressive | `aggressiveTestTrig`: any Phase C test; `aggressiveStrengthFallback`: an SOS/SOW bar when the campaign has no test (an adopted Spring, a re-SOS) | ≥ 55 | ≥ 50 | ≥ 5 |

Confidence is `f_structureConfidence` (L615-616), validation
`f_validationWS` (L936-943), readiness `f_entryReadinessWS` (L958-974). The
direction is the campaign's **outcome** (accumulation → long, distribution →
short), which can oppose the climax side (re-accumulation, re-distribution).
`entryTime` is set once and cleared only when the campaign object is replaced —
**not** by the D→B demotion (L909-930): a demoted campaign never enters again,
even on a later valid Test or LPS (tested). The entry kind is `LPS`,
`STRENGTH` or `TEST` as L1747 computes it.

### Signals

* **Entry** — a market order at the next bar's open, `entry` = the qualifying
  bar's close (the script's `entryPrice`, L1746). For a Test or LPS that bar
  is the pivot's confirmation bar, `pLen` bars after the swing.
* **Stop** (doc 13 D5) — `f_hardLevel` of the outcome side ∓ `stop_atr` (0.5)
  × ATR(14) of the signal bar, fixed for the life of the trade. The script's
  own invalidation is the same level by the same 0.5 ATR, needed on two closes.
* **Target** — none (the script has none); the `2R` variant adds a fixed
  target at 2 × the risk from the signal close.
* **Exits** (D5) — only the structure events of the campaign the trade came
  from, each a `FLATTEN` at the next open (exit reason `SIGNAL_EXIT`):

  | `exit_event` | Pine |
  |---|---|
  | `INVALIDATION` | RS_INVALID in Phase C or D (L1198-1209, L1214) |
  | `DEMOTION` | Phase D → B (L1210-1218) |
  | `PHASE_E_FAILURE` | RS_EEND, three closes back past the middle (L1221) |
  | `PHASE_E_TIMEOUT` | RS_EEND, Phase E older than 300 bars (L1222) |
  | `REPLACED_BY_CLIMAX` | a new SC/BC seeds a campaign in its place (L1237, L1260-1271) |

Metadata of an entry: `trigger` (the alert title), `pine_signal` and
`pine_triggers` (the L1739-1743 names), `entry_kind`, `entry_strictness`, the
bar's `events` (SC, ST, Spring, Test, SOS, LPS …), `confidence`,
`validation`, `readiness` and their floors, the whole `campaign` (type,
climax, outcome, phase, last event, climax/PS/AR/Spring/Test/SOS/LPS times
and prices, range edges, ST, opposite-test and traversal counts, phase start
times, swing length, birth trend), `hard_level`, `stop_basis`
(`spring`/`utad`/`range_low`/`range_high`), `atr`, `trend_score`, `regime`,
`swing_length`, `effort` (`volume`, or `range` on a feed without volume),
`bar_source`, `script_entry/stop/target` (unrounded) and `risk_distance`. An
exit carries `exit_event`, `pine_event`, the values that decided it (`values`:
the hard and invalidation levels and the closes, the range middle and the
closes, Phase E's age), the campaign's serial, phase and outcome, whether it
had gone stale, the new climax and the entry's bar index.

## Params

| Param | Pine | Default |
|---|---|---|
| `entry_strictness` | `entryStrictness`, "Entry Strictness" (L28): `Conservative`, `Standard`, `Aggressive` | `Standard` |
| `target` | — (doc 13 D5): `structure` (no target) or `2R` | `structure` |
| `stop_atr` (0 < x ≤ 10) | — (doc 13 D5): ATR(14) multiples beyond the hard level; 0.5 mirrors `structureInvalidationATR` (L78) | 0.5 |

No other input changes the Auto entry: the ~106 engine thresholds are fixed in
the script (L53-176). `allowHTFOverride`, the label trigger, the schematics,
tables and colours are display options.

## Variants and instances (`config/instances.d/wyckoff_auto.yaml`)

| Instances | Timeframe | Strictness | Target |
|---|---|---|---|
| `wyckoff_auto_standard_5m`, `…_15m`, `…_1h` | 5m, 15m, 1h | Standard | structure |
| `wyckoff_auto_conservative_15m` | 15m | Conservative | structure |
| `wyckoff_auto_aggressive_15m` | 15m | Aggressive | structure |
| `wyckoff_auto_standard_2r_15m` | 15m | Standard | 2R |

Each runs twice (D9): the id above trades MNQ and the six crypto instruments
on **exchange volume**; the same id with `_tickvol` trades XAUUSD, XAGUSD,
NAS100, US30, US500, EURUSD and GBPUSD on OANDA's **tick volume**, and says so
in its name and tags. Effort drives every climax, test, Spring, SOS and LPS,
so the two kinds of volume keep separate accounts and metrics. Twelve
instances, each on its own Paper 50K account with `max_open_positions: 7`
(one position per instrument).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| No higher-timeframe override: the chart-timeframe engine only, one instance per timeframe | Doc 13 / spec recommendation: the override merges up to four engines into one stream (the user's no-combining rule) and picks them by a display utility with wall-clock ages |
| Entries fill at the **next bar's open**; the stop is from the signal bar | The lab's fill model (doc 13 D3); the script stamps the qualifying bar's close |
| An entry whose fill bar opens at or beyond its stop (or 2R target) is skipped (`ORDER_CANCELLED`, meta `skip_entry_beyond_levels`) | Doc 13 D3 |
| An entry whose rounded stop is not below (above) the signal close is a persisted `NO_TRADE` (`STOP_WRONG_SIDE`, `TARGET_WRONG_SIDE`, `LEVELS_NA` without a hard level, `LEVELS_NOT_POSITIVE`); the campaign's entry is used up, as on the chart | Doc 13 D3 |
| A stop and exits the script does not have (above) | Doc 13 D5 |
| A campaign that goes stale (RS_STALE) does not end its trade: it keeps its stop until the next climax takes the empty campaign slot (`REPLACED_BY_CLIMAX`, `campaign_went_stale: true`) | The D5 exits are the script's failure events; staleness is inactivity, not failure. Only one chart campaign exists, so the next climax is the replacement |
| A new entry while a trade is open is ignored (meta `on_opposite_signal: ignore`) | Doc 13 D4 for script 6. In practice it cannot happen: a new campaign only exists once the trade's campaign was replaced, which exits it |
| The Phase C Test, SOS/SOW, LPS/LPSY and Phase E reference-label modes (L29, L2154-2245) are not ported | Spec recommendation: distinct triggers without a quality gate, back-dated `pLen` bars; separate strategies if wanted |
| The phantom opposite-direction label after a demotion (L1798, L2008) is not reproduced | A display artifact of `f_storeConfirmedEntry`'s dedup key; the engine records one entry per campaign, which the port keeps |
| Prices are rounded to the instrument's tick for the order | The lab trades on the tick grid; `metadata.script_*` keep the unrounded numbers |
| The campaign's identity is a serial number (`WS.serial`) | Pine compares campaign objects and climax times (L1811); the strategy needs to know which campaign a trade belongs to |

## Parity notes

* **Path dependence.** The campaign depends on the first bar the engine sees.
  TradingView starts it at the chart's first loaded bar (plan-dependent; Bar
  Replay changes it); the lab starts it at the instance's first warm-up bar.
  Compare only identical bar ranges after a long common history.
* **Pivots with a per-bar length** (`ta.pivothigh/low(pLen, pLen)`, 2-10):
  `>=` on the left, strictly `>` on the right, re-reported when the length
  changes and de-duplicated by pivot bar as the script does (`lastPLBar`, which
  survives resets, L1100-1101, L1319-1324). The tie rule and TradingView's
  behaviour when a series length changes are unverified (doc 14).
* **`math.round` ties go up** (L657, L667, L1087, L1117-1118, L940): Pine's 4.5
  is 5, Python's 4 (`excursion_recovery_limit(6) = 5`, tested).
* **Comparisons** use Pine's 1e-10 tolerance (`gt`, `ge` …), na compares
  false; `ta.atr` and `ta.sma` seed and skip na as in Pine (doc 14).
* **Volume.** On TradingView the OANDA symbols' volume is tick volume, as in
  the lab's OANDA feed, but the counts of two tick feeds need not agree;
  MNQ1! and crypto use exchange volume. A different volume means different
  climaxes and entries.
* **`syminfo.mintick`** floors many ratios; the catalog tick must equal the
  TradingView symbol's (NAS100: the catalog's 0.01, OANDA quotes 0.1 — only
  bars narrower than a tick are affected).
* **Wall-clock age** (L961): readiness counts `(time - lastEventTime) / TF`,
  so weekends count; on an entry bar the age is 0 (tested: a weekend gap
  changes no decision).
* **Not checked against TradingView**: TradingView and the market-data APIs are
  not reachable from the development environment and no chart exports were
  provided. Correctness rests on an independent array transcription of the
  per-bar measures (L1062-1159) run against `measures.py` on synthetic data,
  on targeted tapes for every phase transition, reset path, entry trigger and
  exit, and on invariants over long synthetic and stitched runs
  (`tests/unit/strategies/wyckoff_auto`).

## Warm-up

`meta.warmup_bars = 1000`. The measures are complete after about 300 bars
(SMA 200 plus a trend window ending up to 88 bars back, L1116-1119); a campaign
then needs 100-300 bars from climax to entry, and the campaign state depends on
where history starts, so more history gives a state closer to the chart's.
1000 bars are 3.5 days of 5m and 10.4 days of 15m round the clock (about 5 and
15 calendar days on markets closed at weekends), which `forward.warmup_days:
16` covers. On **1h** they are 42 days round the clock and about 60 calendar
days on the OANDA and CME markets: with the 16-day cap a 1h instance warms up
on about 380 (crypto) or 270 (weekday markets) bars, logs `paper.warmup_short`,
and its first campaigns rest on less history.

The engine costs about 0.12 ms per bar.

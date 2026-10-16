# Script 6 · Wyckoff [theUltimator5] (06_wyckoff_theultimator5.pine) - Pine v6 indicator, 3,199 lines

Source: [`../received/06_wyckoff_theultimator5.pine`](../received/06_wyckoff_theultimator5.pine). Kind: **mixed**. Port complexity: **XL** — The core is a path-dependent Wyckoff campaign state machine of about 1,000 lines, with about 106 hard-coded thresholds, variable-length pivots with back-dated snapshots, three scoring systems, Spring/UTAD probe and provisional-adoption logic, and 7 reset paths. Parity depends on matching TradingView's start bar, volume source, ta.pivot tie rules and math.round. The script defines no stop, exit or position rules, so those must be designed. The optional HTF override multiplies the engines and adds cross-TF selection. Parity checking needs event-by-event comparison against TradingView exports, not just entries.

This spec was produced by the Phase 3 intake review (every line of the script read, earlier descriptions checked against the code). Line numbers refer to the received file. Decisions referenced as D1–D13 are in [docs/13](../../docs/13-phase3-pine-ports.md).

## Setups

### Wyckoff Auto entry (Entry Strictness; Standard default, Conservative and Aggressive as variants)

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Evaluated once per confirmed bar after the whole state machine (L1729-1747), only when _commit (the chart engine runs f_engine(barstate.isconfirmed), L1795), na(s.entryTime) and s.outcome != NONE. Direction = campaign outcome: ACCUM -> LONG, DIST -> SHORT. This can be the opposite of the climax side (re-accumulation or re-distribution, f_typeFrom L700-702). STANDARD (default): (a) standardTestTrig (L1741): a Phase C test confirmed on this bar. That is either the post-Spring/UTAD Test (L1477-1502: Phase C, Spring not yet tested, new pivot low after the Spring bar, pl <= rangeLow + 1.25*ATR[pivot], pl >= SpringLow - 0.15*ATR, score >= 2 of {pivot-bar effort <= 0.8x Spring effort, pivot spread <= 0.8x Spring spread, pivot close-position >= 0.50}) or the no-Spring terminal C-Test from a mature Phase B (L1328-1369: pivot >= 3 bars after the last same-edge test, within 1.25 ATR of the edge, holding the original edge -0.15 ATR, not lower than the reference test -0.15 ATR, quiet effort/spread vs the average of the earlier tests (0.85/1.05 ratios), score >= 2). Plus testScore >= 2 (always true at that point). (b) standardLpsFallback (L1742): an LPS/LPSY confirmed on this bar (L1504-1529: Phase D, pivot after the SOS bar, pl > hardLevel - 0.15*ATR, pl >= rangeHigh - 1.5*ATR, score >= 2 of {pivot eff <= avgEff, pivot spread <= ATR, close-pos >= 0.45}). Both need eQuality (L1735): structure confidence >= 60 (L615-616, 932-934), validation >= 50 (L618-633, 936-943) and entry readiness >= 6 of 9 (L958-974). CONSERVATIVE: LPS/LPSY only, confidence >= 75, readiness >= 7, validation >= 60. AGGRESSIVE: any Phase C test, or an SOS/SOW bar when no test exists (L1740; this includes the provisional-Spring adoption at L1654-1669 and the re-SOS after an LPS at L1678-1693), confidence >= 55, readiness >= 5, validation >= 50. Script price = close of the qualifying bar (L1746). For test and LPS entries that bar is the pivot-confirmation bar, pLen (2-10) bars after the swing. Lab: market order at the next bar's open.
- **Stop:** None. The script defines no stop. The only protective-looking level is the structure-invalidation level f_hardLevel (L723-729): the Spring/UTAD extreme if one exists, otherwise min(origLow, rangeLow) or max(origHigh, rangeHigh). It is used only to reset the campaign once the highest of the last 2 closes is below level - 0.5*ATR (mirrored for shorts) in Phases C and D (L1177-1215).
- **Target / exit:** None. There is no target and no exit signal. Structure events that could be adopted as exits: invalidation reset (L1199-1215); Phase D -> B demotion when the last 3 closes are all past the range midpoint (L1210-1218); Phase E failure by the same 3-close rule (L1221); Phase E older than 300 bars (L1222); stale/idle reset (L1226-1228); RS_DEPART reset (L1643-1676); replacement of the campaign by a new SC/BC seed while in Phase E (L1237, L1260-1271).
- **Position rules:** No position concept. At most one Auto entry per campaign object: s.entryTime is set once (L1745) and cleared only when the WS object is replaced (reset L1233, RS_DEPART L1675, reseed L1269). D->B demotion (L909-930) does NOT clear entryTime, so a demoted campaign can never enter again even if it later produces a valid test or LPS. Only one chart-TF campaign exists at a time, but a new campaign of either direction can seed once the old one is in Phase E or has been reset, so a new entry can come while a previous trade would still be open. There are no daily limits, no session window, no cooldown and no opposite-signal handling. With allowHTFOverride, up to 3 higher-TF engines generate their own entries, which are stored or drawn only when that TF wins the override (L1947-2008).
- **Timeframes:** Runs on the chart TF with no TF restriction. The HTF override scans the next 3 TFs above the chart in the ladder 1,3,5,15,30,60,120,240,D,W,M (L1897, L1909-1916): 1m -> 3/5/15, 5m -> 15/30/60, 15m -> 30/60/120, 1H -> 120/240/D. For the user's stack: separate instances on 5m, 15m and 1H.
- **Sessions (New York):** None. No session, time-of-day or day-of-week filter; every bar on the feed is processed (overnight, Asia and weekend crypto bars included). Time is used only for labels and for the wall-clock age heuristics (L961, L1836).
- **Defaults:** entryStrictness = Standard; Buy/Sell Label Trigger = 'Auto (Entry Strictness)'; allowHTFOverride = true; showEntryPoints = true. About 106 engine thresholds are hard-coded, not inputs (L53-176). Key ones: pivotLen 4, ATR-adaptive between 2 and 10 (adaptiveSwingVolLen 50); atrLen 14; volLen 50; extremeLen 30; climaxVolMult 1.8; climaxSpreadMult 1.5 (x0.8 in strong trends); climaxMinScore 5; minARATR 2.0; maxARBars 30; minPhaseBBars 30; minPhaseBTests 2; springMinPenATR 0.15; springMaxPenATR 2.5; testTolATR 1.25; testExtremeToleranceATR 0.15; breakATR 0.15; strengthMinScore 3; lpsBoundaryATR 1.5; confirmBars 3; structureInvalidationATR 0.5 over 2 closes; phaseDFailBars 3; phaseEMaxBars 300. Entry gates: confidence 75/60/55, readiness 7/6/5, validation floor 60/50/50 (Conservative/Standard/Aggressive).

### Phase C Test reference entry (label mode 'Phase C Test')

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Every post-Spring/UTAD Test (L1477-1502) and every no-Spring C-Test (L1328-1369) while the outcome is set is stored as a LONG/SHORT ENTRY label (L2230-2231, and L2241-2242 for HTF), with no strictness or quality gate. Label time = testTime = time[pLen], the pivot bar (back-dated). Label price anchor = the pivot extreme (testPrice), drawn 1.15*ATR beyond it (L2168-2171). The signal is only knowable on the pivot-confirmation bar, pLen bars later, so a port must act at that bar's close (lab: next open). Direction = outcome.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Labels only. Several can appear per campaign: a Spring after a C-Test clears the terminal test (L1588-1590) and a later Test is stored again; duplicates are removed by time only. Auto entries are drawn as well in this mode (L2155, L2160).
- **Timeframes:** Same as the Auto entry (chart TF plus HTF override).
- **Sessions (New York):** None.
- **Defaults:** Same engine constants; label mode must be set to 'Phase C Test'.

### SOS/SOW reference entry (label mode 'SOS / SOW')

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Fires on every promotion to Phase D (L1613-1641). Conditions: Phase C has aged >= max(3, pLen/2) bars since the Test or Spring; validation >= 60 (+13 bonus when no test); confidence >= 45 (+30 bonus when no test). Then either close > rangeHigh + 0.15*ATR, or the close and previous close (also the close 2 bars back when there was no test) are >= rangeLow + 65% of the range. Strength must also pass: score >= 3 of {relE >= 1.15, spread >= 1.15 ATR, close-pos >= 0.65, bull body >= 0.5 ATR}, or the multi-bar SOS (close - lowest low of 5 bars >= 2 ATR, effort >= 1.10x average, close-pos >= 0.5), or, without a test, a 3-bar rise >= 1 ATR. SOS/SOW also comes from provisional-Spring adoption in Phase B (L1644-1671) and from the re-SOS after an LPS (L1678-1693). Label at the SOS bar's own time (not back-dated) but priced at that bar's HIGH for SOS and LOW for SOW (L1631, L1640, L1682, L1690), not its close. No quality gate.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Labels only. Every re-SOS adds another label (each has a new strTime). Auto entries are also drawn.
- **Timeframes:** Same as the Auto entry.
- **Sessions (New York):** None.
- **Defaults:** Same engine constants; label mode 'SOS / SOW'.

### LPS/LPSY reference entry (label mode 'LPS / LPSY')

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Every LPS/LPSY pivot in Phase D (L1504-1529), stored without a quality gate (L2233, L2244). Label time = lpsTime = time[pLen] (back-dated pivot bar); price anchor = pivot low or high, drawn 1.15 ATR beyond it. Knowable only pLen bars later, at the confirmation bar.
- **Stop:** None.
- **Target / exit:** None.
- **Position rules:** Labels only. lpsTime/lpsPrice are overwritten by each later qualifying pivot (there is no 'already set' check), so a campaign can show several LPS labels. Auto entries are also drawn.
- **Timeframes:** Same as the Auto entry.
- **Sessions (New York):** None.
- **Defaults:** Same engine constants; label mode 'LPS / LPSY'.

### Phase E acceptance reference entry (label mode 'Phase E')

*Fully defined by the script (entry, stop and exit):* **no**

- **Entry:** Fires on the D -> E transition (L1696-1727). With an LPS: >= 3 bars since the LPS confirmation, Phase D age >= max(4, pLen), the lowest of the last 3 closes > rangeHigh (mirrored for shorts), confidence >= 55. Without an LPS: D age >= max(dMin, 5), the lowest of the last 5 closes > rangeHigh, confidence >= 75. Plus the regime check (L1702, L1716). Label at the E bar's time, priced at lastEventPrice, which is that bar's close (L2234, L2245). No quality gate.
- **Stop:** None.
- **Target / exit:** None. The Phase E failure and 300-bar rules end the campaign (L1220-1224).
- **Position rules:** Labels only. One per campaign. Auto entries are also drawn.
- **Timeframes:** Same as the Auto entry.
- **Sessions (New York):** None.
- **Defaults:** Same engine constants; label mode 'Phase E'.

## Data needs

Chart-TF OHLCV only for the core engine. Volume is central: it is the 'effort' measure in every climax, test, Spring, SOS and LPS rule. TradingView uses tick volume for FX/CFD symbols (XAUUSD, XAGUSD, EURUSD, GBPUSD, NAS100, US30, SPX500), real volume for MNQ1!, and exchange volume for crypto. Volume falls back to bar range only if the cumulative volume since the first bar is 0 (L1063-1066). The engine is path-dependent from the first bar processed: TradingView starts it at the first loaded chart bar, and starts each HTF engine 5,000 HTF bars back (calc_bars_count, L176/L1916). Warm-up: SMA(close,200) plus 20 bars (L1116, L1123-1124), SMA(ATR,50) and SMA(effort,50), a trend window of 25-80 bars ending 2-8 bars ago (L1117-1119), highest/lowest over 30 bars. In practice allow >= 300 bars before any signal can appear, and much more for parity. The HTF override (default on) needs OHLCV for the next 3 ladder TFs above the chart, exposed as completed-bar values only (lookahead_on + [1]). No lower-TF intrabar data, no daily/weekly bars beyond the HTF ladder, no external data. syminfo.mintick per symbol is used as a floor in many divisions.

## Engine features needed

- Persistent per-instance state object (the WS campaign, about 100 fields) that survives across bars and resets only through the script's own reset rules; deterministic start bar
- Rolling buffers of >= 2*10+1 bars of OHLCV plus per-bar ATR, effort, avgEff and time, for back-dated pivot-bar snapshots (variable offset pLen)
- Symmetric pivot high/low with a length that can change every bar (series pLen), deduplicated by pivot bar index
- Wilder ATR (ta.atr semantics with SMA seed), SMA, rolling highest/lowest, rolling sum, cumulative volume
- Per-bar volume in the lab bar model (and a range fallback flag per symbol)
- Signal evaluated at bar close, filled as a market order at the next bar's open (existing lab rule; script prices at the signal bar's close)
- User-supplied mandatory stop (the script has none), e.g. a stop from the campaign hard level carried in the signal; MOVE_SL is not needed if the stop is fixed at entry
- Close-based structure exit (flatten at next open) triggered by campaign events: invalidation, D->B demotion, Phase E failure, Phase E 300-bar timeout, campaign replacement
- One-entry-per-campaign counter keyed by a campaign id (not per day)
- Optional: HTF bars aligned without lookahead (completed HTF bar only, as with lookahead_on + [1]) if HTF instances or the override are ported
- Pine-compatible math.round (ties go up) and int() truncation helpers

## Building blocks

- ATR(14) via ta.atr with nz fallback to bar range max(high-low, mintick) during warm-up (L1070-1073); pivot-bar ATR uses atrRaw[pLen]
- Effort series specific to this script: eff = volume, or bar range if cumulative volume <= 0 (a per-symbol switch, not per bar); relE = eff / SMA(eff,50); sprATR = range/ATR; cPos = (close-low)/range
- ATR-adaptive swing length: clamp(PineRound(4 * ATR / SMA(ATR,50)), 2, 10); a campaign freezes it as liveLen[3] at seed (L1085-1089, L1271)
- Pivot high/low variant: ta.pivothigh/pivotlow(high/low, pLen, pLen) with a series length that is the frozen campaign length or the live adaptive length; new-pivot dedup by pivot bar index across campaigns (L1105-1114, L1319-1324)
- Prior-trend score -100..+100 (L573-613): displacement/(ATR*sqrt(n)) clamped to +/-3, x15; efficiency ratio x25; HH/HL vs LH/LL pivot count x20; SMA200 slope +/-10
- Climax detector (SC/BC): downtrend/uptrend, new 30-bar extreme, effort >= 1.8x previous average, range >= 1.5x previous ATR (x0.8 in strong trend), score >= 5 of 6 (L1254-1275); absorption check 3-8 bars later (L1278-1290)
- AR tracker plus ST/opposite-test registration with a robust edge (median of the last 3 tests, capped at the original edge) (L690-698, L775-830, L1292-1462)
- Phase B maturity: age, tests, traversals, bad-test cooldown, effort drying up (L945-956)
- Spring/UTAD probe tracker: pending -> recovery -> provisional or confirmed; adoption on breakout (L1539-1610, L1644-1671)
- SOS/SOW single-bar score and multi-bar SOS (5-bar move >= 2 ATR with effort >= 1.10x) (L1148-1156, L1612-1641)
- LPS/LPSY detector relative to the creek/ice and the hard level (L1504-1529)
- Scores: structure confidence (8 flags), validation (0-100), entry readiness (0-9) (L615-633, L932-974)
- HTF snapshot pattern: run the engine on the HTF, expose the [1] (completed) state via lookahead_on; utility-based override (L1768-1770, L1833-1838, L1909-2006)

## Parity risks

- Path dependence: the whole campaign state depends on the first bar processed. TradingView starts the chart engine at the first loaded bar (plan-dependent history; Bar Replay changes it) and each HTF engine 5,000 HTF bars back. A port that starts on a different bar can disagree for a long time, so compare only over identical bar ranges after long warm-up
- Entry price: the script stamps close of the qualifying bar (L1746); the lab fills at the next bar's open
- Back-dated drawings: Test, C-Test, LPS/LPSY, ST, opposite tests, AR and Phase B/C start labels sit on the pivot or extreme bar, pLen (2-10) bars before they are knowable (L1114 pTime, L1346, L1367, L1384, L1484, L1510). The SC/BC label sits on the climax bar but is only confirmed 3-8 bars later (absorption, L1280). The AR is fixed retroactively. Event alerts fire on the confirmation bar, so labels and alerts disagree in time
- HTF override entries are drawn at the HTF bar's open time but are knowable only after that HTF bar closes (lookahead_on + [1], L1770/L1916). They are stored only when that HTF wins the override on some chart bar (L2006-2008), possibly long after the close or never, so the set of HTF entries the user sees depends on the chart-TF phase competition
- Pine math.round rounds ties up, Python round() is banker's rounding. Real divergences: f_excursionRecoveryLimit(p=6) round(4.5) = 5 vs 4; trendEnd for liveLen=6 round(4.5) = 5 vs 4; outBVis round(p*0.5) for p=5 or 9; adaptLen and f_phaseBMinBars can tie too
- ta.pivothigh/pivotlow with a series length that changes between bars (the live adaptive length when idle, the frozen length inside a campaign). TradingView's tie handling for equal highs/lows and its behaviour when the length changes must be matched exactly; the dedup at L1319-1324 skips pivots whose bar is <= the last pivot bar when the length grows
- Volume semantics: tick volume on TradingView FX/CFD feeds vs whatever the lab feed provides. The range fallback triggers only when cumulative volume == 0 for the whole loaded history. na volume is treated as 0 effort. Different volume means different climaxes, tests and entries
- ta.atr seeding (SMA of the first 14 TRs, then RMA), ta.sma na until full length, and the nz() fallbacks (atr -> range, avgEff -> eff) during warm-up must be replicated
- Wall-clock 'age in bars' heuristics: (time - lastEventTime) / TF seconds (L961, L1836) count weekends and closed sessions as bars. This does not affect entry bars (the age is 0 there) but does affect HTF utility and override selection
- barstate.isconfirmed gating: the chart engine commits state only at bar close (L1795). All historical bars count as confirmed, so a closed-bar port matches. The HTF engine commits every tick (f_engine(true)) but only its [1] value is used, so there is no repaint
- HTF bar boundaries: TradingView aligns 60/120/240/D/W/M bars to each symbol's session (CME 18:00 ET, FX 17:00 ET, crypto 00:00 UTC, DST-aware). The lab aggregator must align identically if HTF instances or the override are compared
- Label cap and rendering: all entry and event labels are rebuilt only on barstate.islast (L3178-3184), and max_labels_count = 500 is shared with event labels, phase letters and schematic labels. On long histories the oldest entry labels are garbage-collected, so the user sees fewer historical entries than the engine generated
- Floating-point equality is used for dedup and campaign identity (e.t == _t at L1783; cClT != trackedHistClimax at L1811); harmless if time is kept as integer ms
- syminfo.mintick floors appear in most ratios. The lab catalog tick size must equal the TradingView symbol's mintick (e.g. XAUUSD 0.01 vs a broker's 0.001)

## Behaviour found in the code

- Dead code: f_drawSelectedEntryLabel (L2253-2264) is never called; selectedEntryLabel is only ever deleted (L3179-3181); the outputs of f_entryDisplayValues (cDispEntry*, efDispEntry*, L2227, L2240) are unused. The Buy/Sell Label Trigger only adds reference labels to the always-visible Auto entries (L2154-2160)
- Phantom opposite-direction entry: f_demoteToB (L909-930) clears the outcome but not entryTime/entryPrice/entryKind. f_storeConfirmedEntry runs every bar with the current outcome (L1798, L2008) and its dedup key includes direction (L1785). If a demoted campaign later takes the opposite outcome, a second LONG/SHORT label appears at the original entry time and price
- No re-entry after demotion: because entryTime survives D->B demotion, a campaign that demotes and later forms a valid Phase C test or LPS cannot produce an entry
- Reference labels are not quality-gated: every Test, C-Test, SOS/SOW, LPS/LPSY and Phase E event with an outcome is stored and drawn as LONG/SHORT ENTRY (L2230-2234, L2241-2245), whatever the Entry Strictness
- SOS/SOW reference labels are priced at the SOS bar's high (SOW: low) (L902, L1631, L1640, L1682, L1690), not its close. Phase E labels use lastEventPrice, the close of the E bar
- Event alerts and labels disagree in time: the SC/BC alert fires at absorption, 3-8 bars after the climax bar where the label sits (L1280-1290 vs L2489-2490); Test, C-Test, ST and LPS alerts fire pLen bars after their back-dated labels
- HTF entries in Auto mode depend on override competition (L1947-1949: farther phase wins, ties broken by a utility that uses wall-clock age and distance from the range). Toggling allowHTFOverride or changing the chart TF changes which entries exist on the chart
- Labels are rebuilt only on the last bar under a shared 500-label cap (L2, L3178-3184). On long histories older entry labels silently disappear
- Pine rounding differences matter in several places (L667, L1118, L1755, L1087, L657): a Python port must use floor(x + 0.5), not round()
- Pivot dedup across campaigns: lastPLBar/lastPHBar persist across resets (L1100-1101, L1319-1324). When pLen grows (e.g. 2 -> 10 after a reset or reseed), pivots on bars <= the last pivot bar are ignored
- Aggressive strictness can enter on the re-SOS after an LPS (L1678-1693, L1740) when no Phase C test was ever recorded
- The no-Spring invalidation level for SC/BC-origin campaigns is the climax extreme (min(origLow, rangeLow)). A stop there can sit far below a C-Test that formed near a robust range edge, which raises the risk per trade
- No session, time or news filter: signals can fire on thin overnight, Asia or weekend bars for all of the user's instruments

## Earlier descriptions, checked

| Verdict | What was said | What the code does |
|---|---|---|
| confirmed | 6.1 Entries: with default 'Standard' strictness, an entry qualifies on a Phase C test or at an LPS/LPSY once quality scores pass; at most one entry per campaign; entry price = close of the qualifying bar; no stop and no target exist. | L1729 gates the entry on _commit, na(s.entryTime) and outcome != NONE. L1741 standardTestTrig = testBit (BIT_TEST, the post-Spring/UTAD Test at L1477-1502, or BIT_CTEST, the no-Spring terminal test at L1328-1369) and eQuality. L1742 standardLpsFallback = lpsBit (L1504-1529) and eQuality. eQuality (L1735) = confidence >= 60, validation >= 50 (L1732: max(45, 60-10)), readiness >= 6 of 9. L1745-1746: entryTime = time, entryPrice = close. entryTime is cleared only when the WS object is replaced (L1233, L1269, L1675). No strategy.* calls, no stop or target lines anywhere. Clarifications: the qualifying bar for a test or LPS is the pivot-confirmation bar, pLen (2-10) bars after the swing. Direction = campaign outcome, which can oppose the climax side. Demotion D->B (L909-930) keeps entryTime, so the campaign can never enter again. |
| partly | 6.2 In 'Auto' label mode the entry is stamped on the bar where it qualified at that bar close; the script entry alerts use the same timing. | True for chart-timeframe entries: stamped on the qualifying bar, known at its close (the label y is close -/+ 1.15 ATR, not the close itself), and the entry alerts fire on that bar. Not true for HTF-override entries shown in Auto mode: they are stamped at the HTF bar's open, known only after it closes, and have no alerts. Alerts follow the chart-TF Auto entry whatever the Buy/Sell Label Trigger setting, and fire even with showEntryPoints off. |
| partly | 6.3 The 'Phase C Test' and 'LPS / LPSY' label modes put the label on the swing low/high itself at the extreme price, although that swing is only confirmed 2-10 bars later (back-dated). | The labels are back-dated to the pivot bar by exactly pLen (2-10) bars and anchored to the pivot extreme, but drawn 1.15 x ATR beyond it, not at it. These modes ADD reference labels on top of the Auto entries, which always remain visible. The reference labels have no strictness or quality gate, so every Test, C-Test or LPS is labeled as an entry, and several can appear per campaign (LPS is overwritten by later pivots; a Spring clears an earlier C-Test). For HTF-override signals the back-dating is pLen HTF bars. |
| partly | 6.4 When a higher timeframe overrides the display, its entries are drawn at the START of the higher-timeframe bar but only known at its close. | Correct for timing: drawn at the HTF bar's open time and known at the earliest when that HTF bar closes. But an HTF entry is stored and drawn only if that HTF wins the override on some chart bar while its campaign still holds the entry, which can be long after the HTF close or never. Its Test/LPS reference labels are back-dated a further pLen HTF bars. |
| partly | 6.5 The script has an invalidation level: the Spring/UTAD extreme, or the range edge if there was no Spring/UTAD (f_hardLevel). | It is a campaign-reset level, not a stop, and it applies only in Phases C and D. Without a Spring/UTAD it is the more extreme of the original edge and the current range edge: for SC/BC-origin campaigns this is effectively the climax extreme, not the robust median range edge. The reset needs 2 closes beyond the level by more than 0.5 ATR; a single touch does not invalidate. Phase A invalidates against the climax price (L1184-1185), and Phase E uses the midpoint rule instead. |
| confirmed | 6.6 The Phase E failure rule is: the last 3 closes all back past the middle of the range. | L1221: eFail = outcome ACCUM ? ta.highest(close,3) < rMid0 : ta.lowest(close,3) > rMid0 (phaseDFailBars = 3, L83; hiCFail/loCFail at L1146-1147; rMid0 from the range at the start of the bar, L1169), with strict inequality. Phase E also ends when it is older than 300 bars (L1222) or when a new SC/BC seeds a campaign while in Phase E (L1237, L1260-1271). The same 3-close-past-mid rule demotes Phase D to B (L1210-1218). The result is a campaign reset (RS_EEND, L1224, L1230-1234), not an exit signal. |
| partly | 6.7 The campaign state machine is roughly 1,000 lines with dozens of thresholds; effort is measured with volume (falls back to range when there is no volume). | The size is right: about 1,000 lines. There are about 106 thresholds, over a hundred rather than 'dozens', and only Entry Strictness among them is user-facing. The range fallback is all-or-nothing per symbol and timeframe: range is used only while cumulative volume since the first loaded bar is zero. Once any volume has appeared, a bar with missing or zero volume counts as zero effort. On TradingView FX/CFD symbols the 'volume' is tick volume. Most rules pair effort with spread/ATR checks. |

## Questions this script raises

- **The script defines no stop, but every lab LONG/SHORT signal requires one. Where should the stop go?** Options: Hard level (Spring/UTAD extreme, else the original climax/AR edge, f_hardLevel) minus/plus 0.5 x ATR(14) at the signal bar; Exact hard level with no buffer; Extreme of the tested swing (Test or LPS pivot) minus/plus 0.15 x ATR; Fixed k x ATR(14) from the entry. Recommended: Hard level -/+ 0.5 x ATR(14), fixed at entry and never widened — It mirrors the script's own invalidation (level - 0.5 ATR, L78, L1199-1215). At entry time (after the Test or in Phase D) the hard level no longer moves, because the Spring extreme only deepens before the Test (L1598).
- **The script has no target and no exit. How should positions be closed?** Options: Structure exit only: flatten at the next open on campaign invalidation, D->B demotion, Phase E failure (3 closes back past the range mid), Phase E > 300 bars, or campaign replacement; Fixed R-multiple target (e.g. 2R) plus the stop; Range-height projection target (breakout edge + range height); Structure exit and 2R target as two separate instances. Recommended: Structure exit plus stop as instance A, and a 2R fixed-target variant as instance B — The structure-exit option uses only rules the script already contains (L1199-1228). A fixed-R variant gives a simple comparison without inventing Wyckoff targets.
- **Which Entry Strictness modes should run?** Options: Standard only; Standard + Conservative + Aggressive as three instances of one strategy. Recommended: All three as separate instances of one strategy — Strictness is a setting of the same setup (only gates and triggers change), which fits the rule that variants run as separate instances.
- **Should the HTF override (chart TF + up to 3 higher TFs, the best structure wins) be ported?** Options: No: run the engine as separate instances per TF (5m, 15m, 1H), each trading its own entries; Yes: replicate the override and merge HTF entries into one stream. Recommended: No override; separate per-TF instances — The override combines several engines into one signal stream, which the user's no-combining rule forbids. It also makes entries depend on display-oriented utility scores and back-dates them to the HTF bar open.
- **Should the reference-label triggers (Phase C Test, SOS/SOW, LPS/LPSY, Phase E) become strategies? The script draws them as LONG/SHORT ENTRY with no quality gate.** Options: Not in the first pass (Auto entry only); Each becomes its own strategy, executed at the confirmation-bar close. Recommended: Not in the first pass; add later as separate strategies if wanted — They are distinct triggers (one strategy each under the user's rules). The Test and LPS labels are back-dated pLen bars, so TradingView visuals overstate them.
- **Volume for instruments without real exchange volume (XAUUSD, XAGUSD, EURUSD, GBPUSD, NAS100, US30, SPX500)?** Options: Use the feed's tick volume; Force the script's range fallback (effort = high - low); Use real volume where available (MNQ1!, crypto) and tick volume elsewhere. Recommended: Real volume for MNQ1! and crypto, tick volume for FX/CFD; parity tests use TradingView-exported OHLCV of the exact same symbol — Effort drives every event. TradingView uses tick volume on those symbols, and a different volume source changes campaigns.
- **What happens if a new entry signal arrives while a position from an earlier campaign is still open?** Options: Ignore new signals while in a position; Close and reverse on an opposite-direction signal; Allow overlapping positions. Recommended: One position per instance; ignore new signals until flat — The script never defines position handling. A new campaign can seed from Phase E (L1237/L1260) while an older trade is still open.
- **Reproduce the display bug where a demoted campaign keeps its entry and can later show a phantom opposite-direction label?** Options: Do not replicate; keep one entry per campaign and no re-entry after demotion; Replicate exactly. Recommended: Do not replicate the phantom label; keep the faithful 'no re-entry after demotion' rule — The phantom is a display artifact (dedup includes direction). The engine itself records one entry.

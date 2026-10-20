# Port S12 — Script 6 Wyckoff campaign engine, Auto entry

The last of the Phase 3 strategies ([doc 13 §13.2](13-phase3-pine-ports.md#132-strategies-to-port))
comes from script 6, "Wyckoff [theUltimator5]": a Wyckoff campaign state machine of
about 1,000 Pine lines with about 106 fixed thresholds, and an Auto entry per campaign
for the chosen Entry Strictness. It is ported as `wyckoff_auto`
(`backend/src/kterminal/strategies/wyckoff_auto/`). Its README holds the rules with the
Pine line numbers, the params, every deviation from the script and the parity notes;
this page is the overview. The schematics, phase shading, tables, the reference-label
entry modes and the higher-timeframe override stay display only (doc 13 D12).

| Module | Ports |
|---|---|
| `wyckoff_engine.py` | `f_engine` (L1060-1764) on the chart timeframe, statement by statement in the script's order: climax detection with the ATR-adaptive pivot length, absorption, the AR, STs, Phase B opposite tests and traversals, Spring/UTAD pending probes and provisional adoption, Spring tests and terminal C-Tests, SOS/SOW promotion, LPS/LPSY, the re-SOS, Phase E acceptance, all seven reset paths (RS_INVALID, RS_ABSORB, RS_NORANGE, RS_DEPART, RS_STALE, RS_DEMOTE, RS_EEND), the D→B demotion, the markup/markdown regime and the Auto entry (L1729-1747) |
| `state.py` | the Pine `WS` campaign type field by field, plus a serial number as the campaign's identity |
| `measures.py` | the per-bar series (L1062-1159) as `kterminal.indicators` objects, one per Pine call site |
| `thresholds.py` | the fixed settings (L53-176), one constant per Pine name |

## How the script's entry maps onto the lab

| Script | Lab |
|---|---|
| `s.entryTime := time`, `s.entryPrice := close` on the bar a trigger of the Entry Strictness fires with its quality gates (confidence, validation, readiness of 9); the "Wyckoff: long/short entry" alerts | a market order at the next open, long for an accumulation outcome, short for a distribution; `entry` = the qualifying bar's close |
| one entry per campaign; `entryTime` survives the D→B demotion, so a demoted campaign never enters again | the same (the engine is the script's), tested |
| no stop | D5: `f_hardLevel` of the outcome side (the Spring/UTAD extreme, else the more extreme of the original and current range edge) ∓ 0.5 × ATR(14) of the signal bar |
| no target, no exit | D5: a `FLATTEN` at the next open on the trade's own campaign events — invalidation (two closes 0.5 ATR beyond the hard level), the D→B demotion, Phase E failure (three closes back past the range middle) or age > 300 bars, replacement by a new climax; the 2R variant adds a fixed target |
| HTF override on by default: up to three higher timeframes' engines compete for the display | not ported: one instance per timeframe |

Signals carry the script's numbers in their metadata: `trigger` (the alert titles, or
`structure exit`), `pine_signal` (`standardTestTrig`, `standardLpsFallback`,
`conservativeLpsTrig`, `aggressiveTestTrig`, `aggressiveStrengthFallback`), the entry
kind, the bar's events, confidence, validation and readiness with their floors, the
campaign (type, outcome, phase, climax, AR, Spring/UTAD, Test, SOS/SOW and LPS/LPSY
times and prices, range edges, test counts), the hard level and stop basis, ATR, trend
score, regime, swing length, the effort source, and the unrounded script entry, stop and
target; an exit carries `exit_event`, the Pine reset that caused it and the values that
decided it.

## Instances

`config/instances.d/wyckoff_auto.yaml` declares them; forward paper trading loads them
with `lab.yaml` ([12.7](12-strategy-lab.md#which-instances-trade)). Every instance has
its own Paper 50K account with `max_open_positions: 7`, one position per instrument
(D10).

| Instance | Timeframe | Entry Strictness | Target |
|---|---|---|---|
| `wyckoff_auto_standard_5m` / `_15m` / `_1h` | 5m, 15m, 1h | Standard (script default) | structure exits |
| `wyckoff_auto_conservative_15m` | 15m | Conservative | structure exits |
| `wyckoff_auto_aggressive_15m` | 15m | Aggressive | structure exits |
| `wyckoff_auto_standard_2r_15m` | 15m | Standard | fixed 2R + structure exits |

Each id trades MNQ and the six crypto instruments on exchange volume; the same id with
`_tickvol` trades XAUUSD, XAGUSD, NAS100, US30, US500, EURUSD and GBPUSD on OANDA's
tick volume and says so in its name (D9). Twelve instances in all.

## Decisions applied

The user did not answer doc 13 §13.6, so every default applies.

| Decision | S12 |
|---|---|
| D3 | market entry at the next open with the stop from the signal bar; skipped when that open is past the stop or target (`skip_entry_beyond_levels` in the meta); no trade (persisted `NO_TRADE`) when the rounded stop is not beyond the signal close |
| D4 | ignore new entries while in a trade (`on_opposite_signal: ignore`) |
| D5 | stop 0.5 ATR(14) beyond the hard level; exits only on the campaign's structure events (a campaign that goes stale keeps its trade until the next climax replaces it); 2R variant |
| D9 | effort is volume everywhere: exchange volume for MNQ and crypto, tick volume for the OANDA feeds, in separately named instances |
| D10 / D11 | 5m, 15m, 1h × Standard; Conservative, Aggressive and 2R on 15m; all 14 instruments |
| D13 | script defaults (the engine's thresholds are not inputs) |

## What is verified, and what is not

| Check | Where |
|---|---|
| An independent array transcription of every per-bar measure (L1062-1159: effort and its all-or-nothing range fallback, ATR, the adaptive length, per-bar-length pivots by brute force, the back-dated pivot snapshot, `f_priorTrendScore`, the windows, the SOS/SOW scores) against `measures.py` on synthetic runs whose swing length switches between live and frozen lengths | `tests/unit/strategies/wyckoff_auto/test_measures.py` |
| The helpers and Pine rounding (ties up: `round(4.5) = 5`) | `…/test_helpers.py` |
| A canonical accumulation and its mirrored distribution walk through SC → absorption → AR + ST (Phase B) → ST2 → Spring (C) → Test → SOS (D) → LPS → Phase E on the scripted bars, with the range edges, robust median, regime and frozen swing length; the regime's 25-bar gate; Spring deepening; a probe dropped as too deep | `…/test_phases.py` |
| Every reset path on its bar (absorption missing, no AR, Phase A/C/D invalidation, Phase B stale and departure, Phase C stale, Phase E failure and 300-bar timeout), the demotion, the reseed by a new climax in Phase E and by a deeper climax in Phase A, provisional Spring adoption; a demoted campaign's new Test cannot enter (and would with `entryTime` cleared) | `…/test_resets.py` |
| Each strictness's entry bar, trigger and kind (Spring Test, C-Test, LPS, adopted-Spring SOS), one entry per campaign, the confidence, validation and readiness gates | `…/test_entries.py` |
| Through the runner: the entry, its D5 stop and metadata, the 2R target, each structure exit, a stop hit before the campaign's own invalidation, the stale-then-replaced trade, D3 skip and wrong-side stop, D4 ignore, determinism, a weekend gap, warm-up | `…/test_strategy.py` |
| Invariants over long synthetic runs and over all scenarios stitched back to back: only the script's phase paths, replacement only through a reset or a climax, one entry per campaign in the outcome's direction, reset counters consistent; exits only for the trade's own campaign | `…/test_invariants.py` |
| Every instance loads, resolves and runs in the lab on synthetic data; the stitched campaigns traded minute by minute at bid/ask through three 15m instances with no unexplained book/account divergence | `…/test_instances.py` |
| The signals and their metadata are stored in PostgreSQL exactly as computed; the accounts audit clean | `tests/integration/strategies/test_wyckoff_auto_postgres.py` |

**Not verified:** parity with TradingView (doc 13 §13.4 step 2). TradingView and the
market-data APIs are not reachable from the development environment and no chart
exports were provided, so no campaign of this port has been compared with a chart and
none has run on live bars yet. The engine is path dependent from its first bar, so a
parity check must use the same bar range and a long common history; pivot ties with a
changing length, tick-volume counts and the symbol's mintick are the known parity risks
(README). Synthetic random walks with uniform volume produce no climaxes, so the lab
smoke run on demo data shows no signals; the scenario tapes provide the trades.

## Warm-up

`warmup_bars` 1000 (the measures need about 300; campaigns are path dependent). 1h needs
about 42 days of crypto and 60 calendar days of weekday markets, so `config/lab.yaml`
sets `forward.warmup_days: 60`; with a smaller cap a 1h instance warms up on fewer bars
and logs `paper.warmup_short`.

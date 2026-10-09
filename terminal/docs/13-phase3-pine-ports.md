# 13. Phase 3 — Porting the received Pine scripts

Ten TradingView scripts were received on 2026-10-08/09. Each is stored word
for word in [`pine/received/`](../pine/received/) and has a detailed spec in
[`pine/specs/`](../pine/specs/). The specs come from an intake review in which
every line of every script was read and every earlier description was checked
against the code. This document turns that review into a plan: what will be
ported, what the engine still lacks, the order of work, and the decisions that
only the user can make.

Ground rules, unchanged from Phase 2: each tradable setup becomes its own
strategy; indicators are never combined unless asked; variants (different
settings) run as separate instances of one strategy, each with its own Paper
50K account; metrics come only from recorded trades; LIVE stays unimplemented.

## 13.1 What was received

| # | Script | Strategies in it | Kept as levels/signals only | Port size |
|---|---|---|---|---|
| 1 | Breakout Targets + ICT Levels + CISD | Main-chart CISD after a sweep; scanner CISD (a second, different model with its own alerts) | Range breakout, trendline break | L |
| 2 | ICT Sweep + Order Flow Models [NY] | Models A, B, C, D | — | XL |
| 3 | NQ Price Action Toolkit | — | FVG/iFVG, session highs/lows, PDH/PDL, opens, NDOG/NWOG, fib range, equal highs/lows, EMA cloud | S |
| 4 | Combined SMC Suite | 200 EMA filtered Parabolic SAR (no stop defined) | Order blocks, channels, EMA taps, 1H/4H breaks, VWAP crosses, sweeps, displacement, PSAR + channel confluence | L |
| 5 | Smart Money Suite v4 | Sniper long/short | Channel breaks, BOS/CHoCH, sweeps, high-confluence state, zones and key levels | M |
| 6 | Wyckoff [theUltimator5] | Auto entry, three strictness levels (no stop or exit defined) | Phase events; reference-label entry modes | XL |
| 7 | Order Flow Desk | — | Volume profile, VWAP bands, delta/CVD, absorption, pools and sweeps, user-entered gamma levels | L |
| 8 | FRVP + ORB + 9/20 EMA | Opening range breakout (no stop or exit defined) | Volume profile, EMA crosses | S |
| 9 | EliteAlgo v32 (replica) | EMA 8/21 cross with 7-check confluence | — | M |
| 10 | Jetstream v2 | SuperTrend flip (no stop defined) | Divergences, zones, take-profit diamonds, oscillator panels | M |

All ten are indicators, not `strategy()` scripts, so TradingView has no trade
list for any of them. Section 13.4 covers how ports are checked.

## 13.2 Strategies to port

| ID | Strategy | Script | Defined by the script | Waiting on |
|---|---|---|---|---|
| S1 | EMA 8/21 cross, 4-of-7 confluence, 200 EMA filter, 1.5 ATR stop, 2R | 9 | Entry, stop, target | — |
| S2 | NY opening range breakout (London ORB as a variant) | 8 | Entry only | D5 |
| S3 | Sniper: BOS through the 40/40 pivot, score ≥ 3 of 4, stop beyond the opposite pivot ± 0.5 ATR, 2R | 5 | Entry, stop, target | — |
| S4 | Model B: 08:00 candle sweep → 1m MSS → displacement-FVG limit | 2 | Entry, stop, target | — |
| S5 | Model A: 20:00 15m-swing sweep → 1m MSS → displacement-FVG limit | 2 | Entry, stop, target | — |
| S6 | CISD after a liquidity sweep, TP1 1R / TP2 2R (main chart model) | 1 | Entry level, stop, targets | D7 |
| S7 | SuperTrend (10, 3) flip; strong-only as a variant | 10 | Entry only | D5 |
| S8 | 200 EMA filtered Parabolic SAR | 4 | Entry and flip exit | D5 |
| S9 | Model C: 1H PD-array bias + 5m FVG tap → 1m IFVG/CISD | 2 | Entry, stop, target | — |
| S10 | Scanner CISD (3/3 pivots), with the A+ grade as a variant | 1 | Entry level, stop, targets | D7 |
| S11 | Model D: candle-estimate absorption at a 15m FVG or key level, 2R | 2 | Entry, stop, target | D9 |
| S12 | Wyckoff auto entry (Standard; Conservative and Aggressive as variants) | 6 | Entry only | D5 |

## 13.3 What the engine still needs

The engine audit found the Phase 2 lab ready for most order types (market at
next open, limits with bar-count expiry, stop entries, per-bar MOVE_SL,
EXIT_*, reverse) but missing the following. Sizes: S < 1 day, M a few days,
L a week or more.

| ID | Work | Needed by | Size |
|---|---|---|---|
| P1 | **Real market data.** Today the lab only has a seeded random walk. Add an importer for 1m CSV / TradingView chart exports (volume type per instrument, no gap filling, MNQ continuous roll matching MNQ1!), persistence to the existing `candles` table, and `kterminal lab run --data … --from … --to …` with automatic warm-up | every port | M |
| P2 | Long-history clients behind a `MarketDataProvider` port (OANDA v20, exchange APIs, a CME vendor), per decision D1 | every port | L |
| P3 | **Pine-parity indicators** in the empty `indicators/` package: EMA/SMA/RMA with Pine seeding, ATR, RSI, DMI/ADX, population stdev, highest/lowest, crossover/cross/change with Pine history semantics, `nz`, Pine `math.round` (ties round up), trading-day VWAP. Each golden-tested against TradingView exports. Indicator code joins `config_hash`, so a fix creates a new strategy version | every port | M |
| P4 | Structure primitives: pivots (fixed and per-bar-variable lengths, Pine tie rules), SuperTrend, Parabolic SAR, WaveTrend, a `bar_index` counter. FVG, order block, CISD and sweep rules differ between scripts and stay inside each strategy | 1, 2, 4, 5, 6, 10 | L |
| P5 | TradingView-compatible higher timeframes: the `lookahead_on` + `[1]` idiom sees a higher-timeframe bar one primary bar later than the lab does today; previous day/week/month high and low built from intraday bars on the trading-day rule (1D/1W/1M are rejected today); 4H bars anchored to the instrument's session | 1, 2, 10 | M |
| P6 | Session windows as instance parameters (20:00–02:00, 08:00–09:00, 09:00–12:00, 09:30–12:00, 18:00–09:30, seven-day variants for crypto), hashed into the version | 1, 2, 8 | S |
| P7 | Order additions: skip a market entry whose next open is already past its stop or target; replace (exit and re-enter on one bar); opposite-signal policy per instance; session-close reasons on time exits; no row for a MOVE_SL that does not move the stop | most ports | M |
| P8 | Resolve the strategy's theoretical book on 1m base bars at bid/ask like the account, and report any book/account disagreement per run | every port | M |
| P9 | **Parity harness:** importers for TradingView chart-data exports and Strategy Tester trade lists; Pine harness copies that plot signals where a script only draws labels; a zero-cost parity cost profile; a comparator that reports matches within one tick and sorts mismatches by known cause | every port | M |
| P10 | Partial exits (optional). Not needed for script 1: with the stop unchanged after TP1, separate TP1-only and TP2-only instances reproduce a 50/50 split | 1 | L |

Documented differences that remain by design: the lab fills market entries at
the next bar's open (the scripts price them at the signal bar's close); when a
bar touches both stop and target the lab assumes the stop, while TradingView's
broker emulator follows open → nearest extreme → other extreme; limits and
stops trigger on bid/ask, not on the mid price.

## 13.4 How a port is checked

1. Golden tests: hand-built bar sequences with known signals.
2. Parity window: you export 2–4 weeks of the same TradingView symbol with the
   script on the chart (or a small harness copy that plots its signals, or a
   `strategy()` wrapper applying the chosen exits). The port runs on a
   zero-cost parity instance over the same bars. Pass = every TradingView
   signal matches on bar, direction and levels within one tick, or the
   difference is one of the documented ones above.
3. Lab instances: the port then runs with normal costs on the long history,
   one Paper 50K account per variant.

## 13.5 Order of work

| Step | Work | Why here |
|---|---|---|
| 1 | P1, P3 (core), P9 → **S1** EliteAlgo | The only script with a complete bracket, closed-bar signals and no session, HTF or limit logic. Proves import → indicators → strategy → lab → parity end to end, and builds the EMA/RSI/ATR/DMI/VWAP set the others reuse |
| 2 | P6, P7 → **S2** NY ORB + London ORB | Explicitly requested; about 40 lines of logic once D5 is answered |
| 3 | P4 (pivots) → **S3** Sniper | Fully specified; the place to validate pivots before the session models depend on them |
| 4 | **S4** Model B | NY session model with no higher-timeframe input; builds the shared sweep → MSS → FVG limit engine |
| 5 | P5 (one-bar lag) → **S5** Model A | Reuses the Model B engine; adds 15m swing levels |
| 6 | P5 (previous D/W/M) → **S6** CISD main | London and NY sweep model; TP1/TP2 as two instances (D7) |
| 7 | **S7** SuperTrend | Small once SuperTrend matches Pine exactly |
| 8 | **S8** Parabolic SAR | Needs an exact SAR port and ADX |
| 9 | **S9** Model C | Three higher-timeframe inputs and a persistent bias state |
| 10 | **S10** Scanner CISD | Four aligned timeframes, session-anchored 4H |
| 11 | **S11** Model D | Volume-dependent; least parity-certain of script 2's models |
| 12 | **S12** Wyckoff | About 1,000 lines of campaign logic with ~106 fixed thresholds; last, once every primitive is proven |

Levels-only scripts (3, 7) and the non-strategy parts of 1, 4, 5, 6 and 10 are
ported only as building blocks when a strategy needs them, keeping each
script's own definitions (fair value gaps, sweeps and pivots differ between
scripts).

## 13.6 Decisions for the user

Each has a default; answering "defaults" accepts all of them.

| ID | Decision | Default |
|---|---|---|
| D1 | **Data source.** Which feeds back the long history, and which exact TradingView symbols do you chart? | Free APIs for long history (OANDA for metals, FX and index CFDs; the exchange APIs for crypto) plus TradingView exports for parity. MNQ from TradingView exports until a paid CME vendor is chosen. Symbols as in the venue profile: OANDA:XAUUSD, XAGUSD, NAS100USD, US30USD, SPX500USD, EURUSD, GBPUSD; CME_MINI:MNQ1!; BINANCE:BTCUSDT.P, BYBIT:SOLUSDT.P, BINANCE:NEARUSDT.P, COINBASE:ZECUSD, HYPERLIQUID:HYPEUSDC.P, BINANCE:PUMPUSDT |
| D2 | **Parity check.** Signal match only, or also trade-by-trade against a `strategy()` wrapper? | Trade-by-trade for S1, S2, S3; signal match for the rest |
| D3 | **Signals priced at the bar close** (scripts 2 C/D, 4, 5, 6, 9, 10). | Fill at the next open, keep the script's stop and target prices, skip the entry if the open has already passed either, skip signals whose stop is on the wrong side |
| D4 | **New signal while a trade is open.** | Script 1: replace. Scripts 4 and 10: stop and reverse on the flip. Scripts 5, 6, 8, 9: ignore until flat (reverse available as a variant) |
| D5 | **Exits for scripts without a stop.** | ORB: stop on the other side of the range, 2R, flat by 16:00 (16:30 London). SuperTrend: exit/reverse on the closed-candle flip, protective stop 1 ATR beyond the line. PSAR: exit/reverse on the closed-candle flip, protective stop at the SAR printed on the signal bar. Wyckoff: stop 0.5 ATR beyond the script's invalidation level, exit on the script's own failure events. Extra instances: ORB midpoint stop with 1R/1.5R/close-at-16:00 targets; SuperTrend and PSAR with the stop trailed on the line; Wyckoff with a fixed 2R target |
| D6 | **Script 2 trades after their window.** | Hold as the script does (until stop, target or the same model's next window), plus a "flat at window end" variant of each model |
| D7 | **Script 1 entry and TP1/TP2.** | Limit at the CISD level, expiring after 12 bars, cancelled if TP1 trades first; TP1-only and TP2-only instances; plus a market-at-next-open comparison instance |
| D8 | **Day, week and month boundaries** (previous day high/low, VWAP reset). | Trading day at 17:00 New York for CFDs, FX, metals and CME; 00:00 UTC for crypto; checked against one TradingView daily bar per instrument |
| D9 | **Volume-driven logic on tick-volume feeds.** | Model D on MNQ and crypto only. Scripts 6 and 9 everywhere, with tick-volume runs labelled as such |
| D10 | **Markets and timeframes.** | 9 and 10: 5m and 15m. 4 and 5: 15m (5m variant). 6: 5m, 15m, 1H. 1: 5m (scanner with 15m/1H/4H bias). 8: 5m with a 15-minute range on MNQ, NAS100, US30, US500 first. 2: 1m. Otherwise all 14 instruments. One Paper 50K account per strategy variant and timeframe, one position per instrument |
| D11 | **Variants in the first pass.** | Script defaults plus: London ORB; script 1 windows "any time", "NY AM", "London + NY AM"; script 5 minimum score 3 and 4; script 6 all three strictness levels; script 10 all flips and strong-only; the D5–D7 variants. Everything else after the defaults pass parity |
| D12 | **What stays levels-only for now.** | Everything in the "kept as levels/signals only" column of 13.1, including the PSAR + channel confluence (it combines modules) |
| D13 | **Your chart settings.** Did you change any inputs from the defaults? | Script defaults. A screenshot of each script's settings is enough to override |

## 13.7 Corrections to earlier descriptions

The intake review checked every description given while the scripts arrived.
Material corrections:

* **Script 1.** The scanner is not display-only: it is a second CISD model
  (3/3 pivots, pivot-only sweeps, no session levels) with its own alerts and
  entry/stop/targets. The stop is the extreme of the most recent opposing
  run, which can sit inside the sweep wick rather than at the sweep extreme.
  The script assumes the CISD-level entry filled without checking.
* **Script 2, Model C.** There is no "toward the draw on liquidity" filter in
  the code; it is only the target. Zone taps before 09:30 count.
* **Script 4, PSAR.** Trailing a stop on the plotted SAR dot can miss flips
  the script makes, so the default is now the script's own close-confirmed
  flip with a fixed protective stop; the trailing stop becomes a variant.
* **Script 5.** "The zone check rarely passes" was not measured and is
  withdrawn. The swing level is a 40-bars-each-side pivot, confirmed 40 bars
  late and never consumed, so the same level can trigger repeatedly.
* **Script 6.** The invalidation level needs two closes beyond it by
  0.5 ATR; about 106 thresholds are fixed in the code.
* **Script 8.** The trigger is a state, not a cross. A breakout blocked by the
  EMA filter does not use up the day's signal, so a long can fire hours later
  when the EMAs turn while price is still above the range. Hiding the
  opening-range drawing switches the signals off.
* **Script 9.** "Strength" is |RSI − 50| × 2, not a count. The 5-bar cooldown
  is shared by longs and shorts. Ties count as bearish, so shorts are slightly
  favoured.
* **Script 10.** BUY/SELL labels and alerts are not confirmed on bar close; on
  the live bar they can appear and vanish.

## 13.8 Known risks

* **Sizing with wide stops.** At 0.5 % risk on 50K ($250), an MNQ stop wider
  than 125 points cannot be sized to one contract. Script 5's 40/40-pivot
  stops, script 6's invalidation stops and script 4's SAR stops will be
  rejected or tiny on some instruments; rejections are recorded.
* **History depth.** TradingView exports of 1m bars cover roughly 1–3 weeks
  depending on the plan: enough for parity, not for statistics or for the
  warm-up of EMA 200 on 15m and the Wyckoff campaign engine.
* **Many comparisons.** About a dozen strategies × variants × timeframes ×
  14 instruments is hundreds of instances; some will look good by chance.
  Proposed rule: no variant is called better without at least 100 closed
  trades and a confirmation on a later period that was not used to choose it.
* **Feeds.** The MNQ roll must match MNQ1!; NEAR, ZEC and PUMP still use
  placeholder specs; HYPE's TradingView symbol is unverified; US and UK clocks
  change on different dates, which shifts London-vs-NY windows for a few
  weeks a year.
* **Holding costs.** Script 2's faithful multi-day holds and the always-in
  scripts 4 and 10 pay swap/funding, which the cost model charges.
* **Licences.** Scripts 3 and 7 are MPL 2.0; script 4's order-block section is
  CC BY-NC-SA 4.0 (non-commercial) and its channel section MPL 2.0; scripts 5
  and 6 name third-party authors without a licence; script 9 replicates a
  commercial product. Private use only; check before distributing.

## 13.9 Scope change against the roadmap

Phase 3 in [doc 10](10-roadmap.md) listed a `SimulatedClock`,
`SimulatedBroker` and fill model. Phase 2's lab already provides that fill
model on its paper accounts, so Phase 3 uses the lab, fed with real data, as
the backtester. `backtest_runs` and signal replay remain in scope after the
first ports.

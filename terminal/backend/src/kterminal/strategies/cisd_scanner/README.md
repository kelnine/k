# cisd_scanner — Scanner CISD with the A+ grade (S10)

Port of the MTF scanner's CISD model of
`terminal/pine/received/01_breakout_targets_ict_cisd.pine` ("Breakout Targets + ICT
Levels + CISD"), spec `terminal/pine/specs/01_breakout_targets_ict_cisd.md`, doc 13
strategy **S10**. The scanner is not display-only (doc 13 §13.7): it runs its own CISD
model, `scanCisd`, on four slot timeframes, prints Entry/SL/TP1/TP2 and a status per
slot, grades a slot's signal A+ when every higher slot's swing-break bias agrees, and
fires alerts. This strategy trades the 5m slot's signals on a 5m chart; the main-chart
model of the same script is `cisd_sweep` (S6). Line numbers below are the received
file's.

| Module | Holds |
|---|---|
| `scanner.py` | `ScanCisd`: `scanCisd` (L778-871) on one slot's bars — 3/3 swings, bias, sweeps, runs, CISD, the slot's trade tracker |
| `strategy.py` | `CisdScanner`: slot 1 on the chart bars, slots 2-4 on the lagged 15m/1h/4h series, the A+ grade, metadata |

The run tracker (`CisdRuns`) and the order handling (`CisdTradeStrategy`, doc 13
D7/D4/D3) come from `cisd_sweep`; the strategy class inherits from that folder, so a
code change there is a new version of S10 too.

## Rules

| Rule | Pine | Port |
|---|---|---|
| Slots | L101-108: 5, 15, 60, 240 minutes, all on | slot 1 = the 5m chart; slots 2-4 = `15m`, `1h`, `4h` (`meta.context_timeframes`) |
| Slot evaluation | L874-877: `request.security(tickerid, tf, scanCisd(higher ? 1 : 0), lookahead = higher ? on : off)` | slot 1 is the chart timeframe (lookahead off, no offset): it runs on the primary bars. Slots 2-4 are higher: `[1]` with `lookahead_on` is the state after the last slot bar that **closed by the chart bar's open** — each runs on `ctx.series(tf, tradingview_lag=True)`, fed bar by bar as they become visible (doc 05 §5.2.1) |
| Swings | L779-794: `ta.pivothigh/low(high/low, 3, 3)` (fixed), `ta.atr(14)` of the slot; a confirmed swing sets the sweep level `swH` and the break level `bosH` | `ScanCisd` (≥ on the left, strictly beyond on the right) |
| Bias | L795-800: a close beyond `bosH` sets `bias = 1` and clears it; then a close beyond `bosL` sets `−1` | Same order; `bias` starts at 0 |
| Sweep | L801-806: `high > swH` stamps `bslBar`, clears `swH`; only this swing counts — no PDH/PW/PM, no session levels, no window | Same; the swept swing's price is kept for the metadata |
| Runs and CISD | L808-840: as the main model (latest opposing run, extreme through the CISD bar, a doji ends a run, consumption on any close through, bearish first); body `>= minBody × nz(sAtr)` of the slot; sweep within `sweepLook` slot bars | `CisdRuns` + the filters. The main model's `bar_index > bullRunX` test, kept by the shared tracker, never matters: a run's first bar cannot close through its own open |
| Slot tracker | L843-870: the latest signal overwrites the slot's trade (entry, stop, TP1/TP2 = ±1R/2R); stop first, then TP2, then TP1; tracking continues after TP1 until TP2 or the stop; `tDir` kept for ever | `ScanCisd._track` (statuses `active`, `TP1 hit`, `TP2 hit`, `stopped`, `TP1 then stopped` in the metadata) |
| A+ | L896-911: `aplus(i)` = the slot has a signal direction and **every enabled higher slot**'s bias equals it, with at least one such slot (`nz` makes a slot without data 0) | `_aplus` with `on2`/`on3`/`on4` |
| New signal | L918: `newSig = d != 0 and tm != nz(tm[1])` — the slot's latest signal changed on this bar | a slot-1 signal on the evaluated bar |
| Alert | L887-889, L923-931: `callText` (`A+ SYMBOL 5m: LONG CISD  Entry …  SL …  TP1 …  TP2 …`), `aplusOnly` limits alerts to A+ | `alert_text` metadata; `aplus_only` trades only A+ signals |

Orders follow `cisd_sweep` (its README, "Orders"): a **LIMIT** at the CISD level with
the run extreme as stop and TP1 or TP2 as target, expiring after 12 bars, cancelled when
TP1 trades first (D7); a new signal cancels the resting order or exits the open trade at
the next open and enters (D4: the scanner's slot tracker also overwrites its trade);
D3 for the market mode. The scanner tracks a trade with no bar limit, so there is no
time exit.

Entry metadata: `trigger` (`Scanner: new signal`, or `Scanner: new A+ signal` — the
script's alertcondition titles), `pine_signal` `scanCisd`, `model` `scanner`, `slot`
`5m`, `cisd_level`, `run_extreme`, `run_start_bar_index`, `run_bars`, `body`, `atr`,
`min_body_points`, `sweep` (`bar_index`, `bars_ago`, `level` `swing high`/`swing low`,
`price`), `aplus`, `aplus_only`, `slots` (per higher slot: `on`, `bias`, its own latest
`signal` with `signal_age`, `signal_status`, `signal_time`, and `last_bar`, the open
time of the newest slot bar it has seen), `alert_text`, and the order fields of
`cisd_sweep` (`script_entry/stop/tp1/tp2`, `risk_points`, `entry_mode`, `target_leg`,
`expires_after_bars`, `cancel_on_tp1`, `bar_index`).

## Params

| Param | Pine input | Default |
|---|---|---|
| `aplus_only` | `aplusOnly` | false (the A+ variant: true) |
| `on2`, `on3`, `on4` | `on2`, `on3`, `on4` (slots 15m, 1h, 4h count for A+) | true |
| `req_sweep`, `sweep_look`, `min_body`, `tp1_r`, `tp2_r` | `reqSweep`, `sweepLook`, `minBody`, `tp1R`, `tp2R` (shared with the main model) | true, 12, 0.3, 1.0, 2.0 |
| `entry`, `target`, `limit_expiry_bars`, `cancel_on_tp1` | — (doc 13 D7) | `limit`, `tp2`, 12, true |

The slot timeframes (`tf1`…`tf4`) are fixed at the script defaults: slot 1 is the 5m
primary timeframe (`meta.timeframes`) and slots 2-4 the context timeframes, which are
part of the version. `on1` is implied (the traded slot), `showScan`, `scanAlerts` and
the table inputs do not change signals. The 3/3 pivot length and ATR 14 are fixed in
the script.

## Variants and instances (`config/instances.d/cisd_scanner.yaml`)

| Instance | Signals | Target |
|---|---|---|
| `cisd_scanner_plain_tp1_5m` | every 5m signal | TP1 |
| `cisd_scanner_plain_tp2_5m` | every 5m signal | TP2 |
| `cisd_scanner_aplus_tp1_5m` | A+ only (15m, 1h and 4h bias agree) | TP1 |
| `cisd_scanner_aplus_tp2_5m` | A+ only | TP2 |

5m with 15m/1h/4h context (D10: "scanner with 15m/1H/4H bias"), all 14 instruments,
script defaults (D13), one Paper 50K account per instance with `max_open_positions: 14`.

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| D7 order handling (limit at the level, 12-bar expiry, TP1 cancel, one target per instance, replace exits at the next open) | As S6: the script assumes a fill at the signal bar and defines no split (see `cisd_sweep`'s README) |
| The A+ variant ignores signals that are not A+: they neither enter nor replace the open trade | With `aplusOnly` the script alerts A+ signals only; a trader following those alerts never sees the others. The scanner table's slot tracker (display only) is still overwritten by them |
| Only slot 1 (5m) is traded; the 15m, 1h and 4h slots supply the bias | Doc 13 D10 ("5m, scanner with 15m/1H/4H bias"); their own signals stay alerts |
| The 4h slot uses the lab's UTC-aligned 4h bars | See the parity notes |

## Parity notes

* **4h bars.** The lab aggregates 4h bars from 00:00 UTC. TradingView anchors them to
  the symbol's session: CME futures (MNQ) at 18:00 New York (18-22-02-06-10-14, the last
  one cut short by the 17:00 close), FX, metals and index CFDs at 17:00 New York
  (22:00 or 21:00 UTC with DST), crypto at 00:00 UTC. For every instrument except the
  crypto ones, the 4h bars group different hours, so the 4h pivots, closes and therefore
  the 4h bias — and the A+ grade — can differ from TradingView's. The 15m and 1h bars
  agree (on-the-hour grid). Session-anchored 4h bars are doc 13 P5's open item (market
  data aggregator).
* **Lag.** A higher slot's bar is seen one chart bar after it closes, exactly like
  `lookahead_on` with `[1]`; the 5m signal itself is the chart bar's.
* **History.** A slot's bias needs a confirmed 3/3 swing and a close beyond it; on 4h
  that is at least 28 hours of bars. The warm-up (36 4h bars) covers it; TradingView's
  bias depends on the chart's loaded history as well, so compare grades only after the
  same warm-up.
* **Bar counts** (`sweepLook`, the pivots) are counted per slot: missing bars on thin
  feeds change them.
* **Fills on bid/ask**: as S6 (book at the mid on 5m bars, accounts on 1m bid/ask; a few
  cancels or replace exits find no order or position in the account).
* **Not checked against TradingView**: TradingView and the market-data APIs are not
  reachable from the development environment and no chart exports were provided.
  Correctness is shown by golden scenarios (an A+ short under bearish 15m/1h/4h biases,
  a long against them, a 4h break not yet visible, the 3/3-only sweep against the main
  model) and by an independent transcription of `scanCisd`, the slot bars and the A+
  grade compared signal for signal on two-week synthetic 1m runs, with and without
  closed weekends, for every input (`tests/unit/strategies/cisd_scanner`).

## Warm-up

`meta.warmup_bars = 36` bars of the largest timeframe (4h): six days round the clock,
1,728 5m bars for ATR(14), and enough 4h bars for the swing breaks of the 4h bias. It
fits the default `forward.warmup_days: 10`. As for S6, a limit placed during warm-up is
forgotten after 12 bars; a TP1 cancel or replace in the first live bars may then send
one `EXIT_*` that finds no order (`NO_MATCHING_POSITION`).

## Licence

The script carries no licence statement (doc 13 §13.8: private use).

# elitealgo_ema_confluence — EliteAlgo v32 EMA 8/21 cross, 4-of-7 confluence (S1)

Port of `terminal/pine/received/09_elitealgo_v32_replica.pine` ("EliteAlgo v32
pulse ai (replica+)"), spec `terminal/pine/specs/09_elitealgo_v32_replica.md`,
doc 13 strategy **S1**. The script is an indicator: it draws signals and an
entry/stop/target bracket but tracks no position. Line numbers below are the
received file's.

## Rules

| Rule | Pine | Port |
|---|---|---|
| Indicators | L37-45: `ta.ema(close, 8/21/200)`, `ta.rsi(close, 14)`, `ta.atr(14)`, `ta.vwap(hlc3)`, `ta.dmi(14, 14)`, `pulse = ta.ema(close, 5) − ta.ema(close, 60)`, `pHist = pulse − ta.ema(pulse, 20)` | `Ema`, `Rsi`, `Atr`, `Vwap`, `Dmi`, `Macd(5, 60, 20).hist`, each updated on every bar like the script's unconditional calls |
| VWAP anchor | `ta.vwap(hlc3)` resets on `timeframe.change("1D")` | Reset on the first bar of each **trading day** of the instrument (`ctx.periods.current("D")`): 17:00 New York (DST-correct) for metals, FX, index CFDs and MNQ, 00:00 UTC for crypto (doc 13 D8). na until the first boundary seen |
| Confluence | L53: `bullCnt` = one point each for `close > emaT`, `emaF > emaS`, `rsi > 50`, `diP > diM`, `pHist > 0`, `close > open`, `close > vwap`; L54 `bearCnt = 7 − bullCnt` | `bull_count()` with Pine's comparisons (`gt`: 1e-10 tolerance, false with na), so **ties and na count as bearish** |
| Cooldown | L59-60, L93: `coolOK = na(lastSigBar) or bar_index − lastSigBar >= 5`; `lastSigBar` set on every long or short signal | `ctx.bar_index` (warm-up included); restarted by every script signal — also one the position rules then ignore, and one skipped by the D3 wrong-side rule. Shared by both directions |
| Long | L61, L64: `ta.crossover(emaF, emaS) and bullCnt >= 4 and close > emaT and coolOK and confirmed` | Same, on the closed bar (`confirmed` is always true for closed bars) |
| Short | L62, L65: `ta.crossunder(emaF, emaS) and bearCnt >= 4 and close < emaT and coolOK and confirmed` | Same |
| Stop / target | L95-98: `risk = atr × 1.5`, stop `close ∓ risk`, target `close ± 2 × risk` | Same, from the signal bar's close and ATR(14), fixed for the life of the trade (no trailing, no other exit) |

Signals carry the script's numbers in `metadata`: `pine_signal` (`longSig` /
`shortSig`), `trigger` (`Buy` / `Sell`), `stars` (L69-71), `bull_count`,
`bear_count`, the seven `checks`, every indicator value, `strength` (L74),
`script_entry/stop/target` (unrounded), `bar_index` and `bar_source` (the
feed). `confidence` is the script's L73 `conf` / 100 (0.14 / 0.43 / 0.71 / 1.0).

## Params

| Param | Pine input | Default |
|---|---|---|
| `fast_len`, `slow_len`, `trend_len` | `fastLen`, `slowLen`, `trndLen` | 8, 21, 200 |
| `rsi_len`, `adx_len`, `adx_smoothing`, `atr_len` | `rsiLen`, `adxLen`, `adxSm`, `atrLen` | 14, 14, 14, 14 |
| `pulse_fast`, `pulse_slow`, `pulse_signal` | `pF`, `pSl`, `pSig` | 5, 60, 20 |
| `min_confluence` (0-7) | `minConfl` | 4 |
| `use_trend_filter` | `useTrendF` | true |
| `cooldown_bars` (≥ 0) | `coolBars` | 5 |
| `sl_mult` (≥ 0.1), `rr_ratio` (≥ 0.1) | `slMult`, `rrRatio` | 1.5, 2.0 |

`waitClose` is not a param: the lab evaluates closed bars only, which is the
script's default (`true`). Display inputs (colours, labels, panel, regime and
session texts, L47-49 and L75-78) do not change signals and are not ported.

## Instances (`config/instances.d/elitealgo_ema_confluence.yaml`)

| Instance | Timeframe | Opposite signal while in a trade |
|---|---|---|
| `elitealgo_ema_confluence_main_5m` / `_main_15m` | 5m / 15m | ignored (doc 13 D4 default for script 9) |
| `elitealgo_ema_confluence_reverse_5m` / `_reverse_15m` | 5m / 15m | reverses at the next open (D4 variant) |

All 14 instruments (D10), script defaults (D13), one Paper 50K account per
instance with `max_open_positions: 14` (one position per instrument).

## Deviations from the script (and why)

| Deviation | Reason |
|---|---|
| Entries fill at the **next bar's open**; stop and target stay at the levels computed from the signal close | The lab's fill model (doc 01 §1.7, doc 13 D3); the levels match the lines and alert the user sees |
| An entry whose fill bar opens at or beyond its stop or target is skipped (`ORDER_CANCELLED`, `OPEN_BEYOND_STOP` / `OPEN_BEYOND_TARGET`; meta `skip_entry_beyond_levels`) | Doc 13 D3: after a session break the drawn bracket is no longer tradable |
| A signal whose rounded stop (or target) is not beyond the entry is not traded: a persisted `NO_TRADE` with reason `STOP_WRONG_SIDE` / `TARGET_WRONG_SIDE` / `LEVELS_NA` / `LEVELS_NOT_POSITIVE` and the script's metadata. It still restarts the cooldown | Doc 13 D3; the lab needs a valid bracket, the script would still draw the lines |
| An opposite signal while in a trade is ignored (main) or reverses (variant); a same-direction signal is ignored (one position per instrument) | The script has no position: it redraws the bracket on every signal. Doc 13 D4; pyramiding is not supported |
| A trade ends only at its stop or target (stop first when one bar reaches both) | The script never checks its lines (L99-106); the lab's conservative bar resolution (doc 13 §13.3) |
| VWAP anchored on the catalog's trading day | Doc 13 D8; TradingView's per-symbol daily session may differ (see parity) |
| VWAP before the first trading-day boundary of the history is na (the check counts bearish) | `Vwap` convention (doc 14 §14.4); irrelevant after warm-up |

## Parity notes

* **Volume.** The VWAP check needs bar volume. OANDA feeds (XAUUSD, XAGUSD,
  NAS100, US30, US500, EURUSD, GBPUSD) carry **tick volume**, crypto and MNQ
  exchange volume; `metadata.bar_source` names the feed, so tick-volume
  signals can be labelled (doc 13 D9). Zero volume makes the VWAP na, which is
  a bearish point on every bar.
* **Anchor.** CME's daily session starts at 18:00 New York; the catalog's
  17:00 rule gives the same first bar because CME has no bars between 17:00
  and 18:00. Other feeds' TradingView sessions are unverified (doc 13 D8).
* **Path dependence.** EMA200 and the Wilder averages inside RSI/ATR/DMI depend
  on where history starts: compare with TradingView only after ≥ 1000 bars.
* **Cooldown.** It counts bars, so a feed with missing bars (thin crypto
  minutes, data gaps) can block or allow different crosses than TradingView.
* **Not checked against TradingView**: TradingView is not reachable from the
  development environment and no exports were provided. Correctness is shown
  by golden scenarios and by an independent array-based transcription of the
  script (`tests/unit/strategies/elitealgo_ema_confluence`).

## Warm-up

`meta.warmup_bars = 1000` (spec: ≥ 1000 for EMA200 and the Wilder averages);
the strategy also reads `ctx.periods`, so forward warm-up covers at least
`period_warmup_bars("D", tf)`. With the default `forward.warmup_days: 10` a
15m instance gets fewer bars than that on markets that close at weekends
(`paper.warmup_short` is logged); its first signals then rest on a less
converged EMA200.

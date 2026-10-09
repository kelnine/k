# Pine sources

`received/` holds the TradingView scripts exactly as they were sent. They are
the reference for the Python ports and for parity checks, and are never
edited; a port that needs a different behaviour says so in its own module.

Each tradable setup in a script becomes its own strategy. Setups are never
combined unless explicitly asked for.

`specs/` holds a detailed spec of each script from the Phase 3 intake review:
exact rules with line numbers, data needs, parity risks and the behaviour
found in the code. The porting plan and the open decisions are in
[docs/13](../docs/13-phase3-pine-ports.md).

| # | File | Script | Setups to port |
|---|------|--------|----------------|
| 1 | `01_breakout_targets_ict_cisd.pine` | Breakout Targets + ICT Levels + CISD | Main-chart CISD after a liquidity sweep; scanner CISD (a second model with its own alerts). Range breakout and trendline break as signals |
| 2 | `02_ict_sweep_order_flow_models.pine` | ICT Sweep + Order Flow Models [NY] | A · 8 PM range sweep; B · 8 AM candle sweep; C · PD-array bias + IFVG/CISD; D · order-flow absorption |
| 3 | `03_nq_price_action_toolkit.pine` | NQ Price Action Toolkit | None yet: levels and zones only (FVG/iFVG, session highs/lows, PDH/PDL, 00:00 and 09:30 opens, NDOG/NWOG, fib dealing range, equal highs/lows, EMA 9/21 cloud), no entry or exit rules |
| 4 | `04_combined_smc_suite.pine` | Combined SMC Suite | 200 EMA filtered Parabolic SAR (entry and flip exit, no stop). Signals without exits: order blocks, breakout channels, EMA pullback taps, previous 1H/4H high/low and VWAP crosses, sweeps, displacement |
| 5 | `05_smart_money_suite_v4.pine` | Smart Money Suite v4 [AlgoAlpha] | Sniper long/short (BOS entry, swing stop, 2R target). Signals without exits: channel breakouts, BOS/CHoCH, liquidity sweeps, high-confluence score |
| 6 | `06_wyckoff_theultimator5.pine` | Wyckoff [theUltimator5] | Wyckoff entry (Phase C test or LPS/LPSY, by strictness); entries only, no stop or target. Phase events (SC/BC, Spring/UTAD, SOS/SOW, Phase E) as signals |
| 7 | `07_order_flow_desk.pine` | Order Flow Desk [v6] | None yet: levels and events only (session volume profile, VWAP bands, delta/CVD, absorption, equal-high/low pools and sweeps, user-entered gamma levels), no entry or exit rules |
| 8 | `08_frvp_orb_ema.pine` | FRVP + ORB + 9/20 EMA | Opening range breakout (first close outside the 09:30–09:45 range, EMA 9/20 filter); entries only, no stop or target. Volume profile and EMA crosses as levels/signals |
| 9 | `09_elitealgo_v32_replica.pine` | EliteAlgo v32 pulse ai (replica+) | EMA 8/21 cross with 7-check confluence and 200 EMA filter (1.5 ATR stop, 2R target) |
| 10 | `10_jetstream_v2.pine` | Jetstream v2 | SuperTrend (10, 3) flip, stop and reverse; BUY+/SELL+ (WaveTrend still washed out) as a setting of the same strategy. Take-profit diamonds, WaveTrend divergences and supply/demand zones as signals/levels |

The same idea often appears in several scripts with different details (fair
value gaps in 1, 2, 3 and 5; sweeps in 1, 2, 4, 5 and 7). Each port uses the
definition from its own script, so a strategy matches the chart it came from.

Licences travel with the code. Scripts 3 and 7 are MPL 2.0. Script 4
contains LuxAlgo's Order Block Detector (CC BY-NC-SA 4.0: attribution,
non-commercial, same licence) and AlgoAlpha's Smart Money Breakout Channels
(MPL 2.0); a port of either keeps its own file, the original notice and the
same licence. Scripts 5 and 6 name third-party authors but state no licence,
so they are treated as private use only. Scripts 1, 2, 8, 9 and 10 carry no notice.

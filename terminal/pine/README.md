# Pine sources

`received/` holds the TradingView scripts exactly as they were sent. They are
the reference for the Python ports and for parity checks, and are never
edited; a port that needs a different behaviour says so in its own module.

Each tradable setup in a script becomes its own strategy. Setups are never
combined unless explicitly asked for.

| # | File | Script | Setups to port |
|---|------|--------|----------------|
| 1 | `01_breakout_targets_ict_cisd.pine` | Breakout Targets + ICT Levels + CISD | CISD after a liquidity sweep; range breakout |
| 2 | `02_ict_sweep_order_flow_models.pine` | ICT Sweep + Order Flow Models [NY] | A · 8 PM range sweep; B · 8 AM candle sweep; C · PD-array bias + IFVG/CISD; D · order-flow absorption |
| 3 | `03_nq_price_action_toolkit.pine` | NQ Price Action Toolkit | None yet: levels and zones only (FVG/iFVG, session highs/lows, PDH/PDL, 00:00 and 09:30 opens, NDOG/NWOG, fib dealing range, equal highs/lows, EMA 9/21 cloud), no entry or exit rules |
| 4 | `04_combined_smc_suite.pine` | Combined SMC Suite | 200 EMA filtered Parabolic SAR (entry and exit). Signals without exits: order blocks, breakout channels, EMA pullback taps, previous 1H/4H high/low and VWAP crosses, sweeps, displacement |
| 5 | `05_smart_money_suite_v4.pine` | Smart Money Suite v4 [AlgoAlpha] | Sniper long/short (BOS entry, swing stop, 2R target). Signals without exits: channel breakouts, BOS/CHoCH, liquidity sweeps, high-confluence score |

Licences travel with the code. Script 4 contains LuxAlgo's Order Block
Detector (CC BY-NC-SA 4.0: attribution, non-commercial, same licence) and
AlgoAlpha's Smart Money Breakout Channels (MPL 2.0); a port of either keeps
its own file, the original notice and the same licence. Script 5 names
AlgoAlpha but states no licence, so it is treated as private use only.

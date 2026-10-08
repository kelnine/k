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

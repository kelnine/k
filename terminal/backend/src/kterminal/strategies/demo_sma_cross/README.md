# demo_sma_cross — DEMO ONLY

A deliberately simple SMA crossover used to demonstrate the strategy lab
(isolation, versioning, per-instance paper accounts). It is not a trading
idea and should not be traded.

| Param | Default | Meaning |
|---|---|---|
| `fast` / `slow` | 9 / 21 | SMA lengths on the primary timeframe |
| `range_bars` | 14 | bars averaged for the stop distance |
| `stop_range_mult` | 1.5 | stop = mult × average bar range |
| `reward_risk` | 2 | target = R:R × stop distance |

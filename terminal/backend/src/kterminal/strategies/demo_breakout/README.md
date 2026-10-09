# demo_breakout — DEMO ONLY

Channel breakout on the primary timeframe with an optional trend filter from
the last *closed* 1-hour bar. Demonstrates multi-timeframe context (1H context
→ 5m entries) without look-ahead. Not a trading idea.

| Param | Default | Meaning |
|---|---|---|
| `channel_bars` | 20 | look-back for the breakout channel |
| `trend_filter` | true | require the 1h close above/below its SMA |
| `trend_sma` | 10 | 1h SMA length for the filter |
| `reward_risk` | 1.5 | target = R:R × (entry − channel midpoint) |

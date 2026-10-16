# Appendix A. Performance Metric Definitions

Fixed definitions make strategy comparisons meaningful. All metrics are
computed from **closed trades** (`trades.status = 'CLOSED'`) using `net_pnl`
(after commission and swap) unless stated otherwise. A trade with
`net_pnl > 0` is a win, `< 0` a loss, `= 0` a scratch (counted in totals,
excluded from win/loss averages).

| Metric | Definition |
|---|---|
| Total trades | `N` closed trades |
| Winning / losing trades | `W = count(net_pnl > 0)`, `L = count(net_pnl < 0)` |
| Win rate | `W / (W + L)` |
| Gross profit | `Σ net_pnl` over wins |
| Gross loss | `Σ net_pnl` over losses (reported as a negative number) |
| Net P&L | `gross profit + gross loss` |
| Profit factor | `gross profit / |gross loss|`; `∞` shown as "—" when there are no losses |
| Average winner / loser | `gross profit / W`, `gross loss / L` |
| R multiple (per trade) | `net_pnl / initial_risk`, where `initial_risk = |entry_fill − initial_stop| × qty × value/unit` (initial stop, not a moved stop) |
| Realized R | `Σ R` over all closed trades |
| Average R | `Realized R / N` |
| Expectancy | `win_rate × avg_winner + (1 − win_rate) × avg_loser` in currency; **expectancy (R)** = average R. The leaderboard uses expectancy in R so differently sized accounts compare fairly |
| Max drawdown | Largest peak-to-trough decline of the **mark-to-market equity curve** (`equity_snapshots`), in currency and % of peak. Backtests also report closed-trade drawdown |
| Average drawdown | Mean depth of all distinct drawdown episodes (peak → recovery to a new peak) |
| Sharpe ratio | `mean(daily returns) / stdev(daily returns) × √252`, risk-free rate 0, from daily account returns. Reported only when there are ≥ 30 trading days with ≥ 20 trades; otherwise "insufficient data" |
| Consecutive wins / losses | Longest streak of wins / losses by exit time |
| Long / short performance | Every metric above computed separately for `direction = LONG` and `SHORT` |
| Average holding time | Mean `exit_time − entry_time` |
| Avg slippage | Mean `entry_slippage` and `exit_slippage` in ticks (forward/live) |

## Breakdowns

Every metric can be grouped by: **strategy**, **symbol**, **timeframe**,
**trading session** (session at entry, defined per instrument, e.g. Asia /
London / New York / overlap), **day** (trading day per the risk profile's
day boundary), **ISO week**, **month**, and **direction**.

## Leaderboard

Default ranking key: **expectancy (R)**, with ties broken by profit factor.
Every leaderboard row shows `N` and is flagged "low sample" below 30 trades.
Columns: strategy, mode, N, win rate, net P&L, profit factor, expectancy (R),
realized R, max DD %, Sharpe (when appropriate), longest losing streak.

Comparisons are only labelled "identical conditions" when strategies ran on
accounts with the same starting balance, the same risk-profile version, the
same instruments, the same data fingerprint (backtests) or the same calendar
window (forward tests).

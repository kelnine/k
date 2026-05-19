"""Generates the end-of-day performance report."""
import logging
from datetime import date
from collections import defaultdict

from bot.state import TradingState, ClosedTrade

logger = logging.getLogger(__name__)


class DailyReporter:
    def generate(self, state: TradingState) -> str:
        today = date.today().isoformat()
        trades = state.today_closed_trades()
        all_trades = state.all_closed_trades()

        lines = [
            f"Date: {today}",
            f"Balance: ${state.balance:,.2f}",
            "",
        ]

        if not trades:
            lines.append("No completed trades today.")
        else:
            wins = [t for t in trades if t.pnl > 0]
            losses = [t for t in trades if t.pnl <= 0]
            total_pnl = sum(t.pnl for t in trades)
            win_rate = len(wins) / len(trades) * 100 if trades else 0

            lines += [
                f"Trades Today: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)}",
                f"Win Rate: {win_rate:.0f}%",
                f"Total P&L: ${total_pnl:+,.2f}",
                "",
            ]

            # Best and worst tickers by P&L
            ticker_pnl: dict[str, float] = defaultdict(float)
            for t in trades:
                ticker_pnl[t.ticker] += t.pnl

            if ticker_pnl:
                best_ticker = max(ticker_pnl, key=ticker_pnl.__getitem__)
                worst_ticker = min(ticker_pnl, key=ticker_pnl.__getitem__)
                lines += [
                    f"Best Ticker:  {best_ticker} (${ticker_pnl[best_ticker]:+,.2f})",
                    f"Worst Ticker: {worst_ticker} (${ticker_pnl[worst_ticker]:+,.2f})",
                    "",
                ]

            lines.append("Trades:")
            for t in trades:
                pnl_str = f"${t.pnl:+.2f} ({t.pnl_pct:+.1%})"
                lines.append(
                    f"  {t.ticker} {t.option_type.upper()} ${t.strike:.0f} exp {t.expiry}"
                    f" → {t.exit_reason} | {pnl_str}"
                )

        # All-time summary
        if all_trades:
            all_wins = [t for t in all_trades if t.pnl > 0]
            all_pnl = sum(t.pnl for t in all_trades)
            lines += [
                "",
                f"All-Time: {len(all_trades)} trades | "
                f"Win rate {len(all_wins)/len(all_trades)*100:.0f}% | "
                f"Total P&L ${all_pnl:+,.2f}",
            ]

        lines.append("")
        lines.append("PAPER TRADING ONLY — No real money at risk.")

        return "\n".join(lines)

"""
Calculates position sizes and stop/target levels.
Risk is capped at MAX_RISK_PCT of current account balance per trade.
"""
import logging
import math

from config import MAX_RISK_PCT, STOP_LOSS_PCT, TP1_PCT, TP2_PCT

logger = logging.getLogger(__name__)


class RiskManager:
    def calculate_contracts(
        self,
        balance: float,
        option_price: float,
    ) -> int:
        """
        Returns the number of contracts to buy given the current balance and
        the option's per-contract price (in dollars, i.e. bid/ask midpoint).

        Each contract covers 100 shares, so cost = contracts * option_price * 100.
        Max risk is MAX_RISK_PCT of balance; stop loss is STOP_LOSS_PCT of entry.
        """
        max_loss_dollars = balance * MAX_RISK_PCT
        contract_cost = option_price * 100
        max_loss_per_contract = contract_cost * abs(STOP_LOSS_PCT)

        if max_loss_per_contract <= 0:
            return 0

        contracts = math.floor(max_loss_dollars / max_loss_per_contract)
        if contracts < 1:
            if contract_cost <= balance * MAX_RISK_PCT / abs(STOP_LOSS_PCT):
                contracts = 1
            else:
                logger.warning(
                    f"Option price ${option_price:.2f} too expensive for 2% risk "
                    f"(balance=${balance:.2f}). Skipping."
                )
                return 0

        # Never spend more than 10% of balance in one trade
        max_spend = balance * 0.10
        while contracts > 0 and contracts * contract_cost > max_spend:
            contracts -= 1

        return contracts

    def stop_loss_price(self, entry_price: float) -> float:
        return round(entry_price * (1 + STOP_LOSS_PCT), 4)

    def tp1_price(self, entry_price: float) -> float:
        return round(entry_price * (1 + TP1_PCT), 4)

    def tp2_price(self, entry_price: float) -> float:
        return round(entry_price * (1 + TP2_PCT), 4)

    def trail_stop_price(self, current_price: float) -> float:
        """Trail stop 20% below current price after TP1."""
        return round(current_price * 0.80, 4)

    def check_exit(
        self,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        tp1: float,
        tp2: float,
        tp1_hit: bool,
        trail_stop: float | None,
    ) -> tuple[str | None, float | None]:
        """
        Returns (exit_reason, exit_price) or (None, None) if no exit triggered.
        Checked in priority order: SL → trail → TP2 → TP1.
        """
        effective_stop = trail_stop if (tp1_hit and trail_stop is not None) else stop_loss

        if current_price <= effective_stop:
            reason = "TRAIL" if (tp1_hit and trail_stop is not None) else "SL"
            return reason, current_price

        if current_price >= tp2:
            return "TP2", current_price

        if not tp1_hit and current_price >= tp1:
            return "TP1", current_price

        return None, None

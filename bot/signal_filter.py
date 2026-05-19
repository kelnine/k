"""
Filters raw flow alerts against the strategy criteria and detects
repeated same-direction flow within a rolling time window.
"""
import logging
from datetime import datetime, timedelta

from config import (
    WATCHLIST,
    MIN_PREMIUM,
    MAX_DTE,
    MIN_DTE,
    VALID_FLOW_TYPES,
    REPEAT_FLOW_WINDOW_MINUTES,
    REPEAT_FLOW_MIN_COUNT,
)

logger = logging.getLogger(__name__)


class SignalFilter:
    def filter(
        self,
        alerts: list[dict],
        seen_ids: set[str],
        recent_signals: list[dict],
    ) -> list[dict]:
        """
        Returns alerts that:
          - Are for a watched ticker
          - Haven't been seen before
          - Meet premium, DTE, volume/OI, and flow-type thresholds
          - Have at least REPEAT_FLOW_MIN_COUNT same-direction hits in the window
            (the current alert itself counts as one)
        """
        now = datetime.utcnow()
        passed: list[dict] = []

        for alert in alerts:
            if alert["id"] in seen_ids:
                continue

            if not self._passes_hard_criteria(alert):
                continue

            # Add to recent signals for repeat-detection
            signal_entry = {**alert, "_seen_at": now}
            recent_signals.append(signal_entry)

            # Prune old entries from the rolling window
            cutoff = now - timedelta(minutes=REPEAT_FLOW_WINDOW_MINUTES)
            recent_signals[:] = [s for s in recent_signals if s["_seen_at"] >= cutoff]

            repeat_count = self._count_same_direction(
                alert["ticker"], alert["option_type"], recent_signals
            )

            if repeat_count >= REPEAT_FLOW_MIN_COUNT:
                logger.info(
                    f"Signal: {alert['ticker']} {alert['option_type'].upper()} "
                    f"| Strike: {alert['strike']} | Expiry: {alert['expiry']} "
                    f"| Premium: ${alert['premium']:,.0f} | Vol/OI: {alert['volume']}/{alert['open_interest']} "
                    f"| Type: {alert['execution']} | Repeats: {repeat_count}"
                )
                passed.append(alert)
            else:
                logger.debug(
                    f"Filtered out (repeat {repeat_count}<{REPEAT_FLOW_MIN_COUNT}): "
                    f"{alert['ticker']} {alert['option_type']}"
                )

        return passed

    def _passes_hard_criteria(self, alert: dict) -> bool:
        ticker = alert["ticker"]
        if WATCHLIST and ticker not in WATCHLIST:
            return False

        if alert["premium"] < MIN_PREMIUM:
            logger.debug(f"{ticker}: premium ${alert['premium']:,.0f} < ${MIN_PREMIUM:,}")
            return False

        dte = alert["dte"]
        if not (MIN_DTE <= dte <= MAX_DTE):
            logger.debug(f"{ticker}: DTE {dte} out of range [{MIN_DTE},{MAX_DTE}]")
            return False

        vol = alert["volume"]
        oi = alert["open_interest"]
        if oi > 0 and vol <= oi:
            logger.debug(f"{ticker}: volume {vol} not > OI {oi}")
            return False

        execution = alert["execution"]
        if VALID_FLOW_TYPES and not any(ft in execution for ft in VALID_FLOW_TYPES):
            logger.debug(f"{ticker}: execution '{execution}' not in {VALID_FLOW_TYPES}")
            return False

        return True

    def _count_same_direction(
        self, ticker: str, option_type: str, recent_signals: list[dict]
    ) -> int:
        return sum(
            1
            for s in recent_signals
            if s["ticker"] == ticker and s["option_type"] == option_type
        )

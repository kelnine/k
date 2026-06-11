"""Risk engine: ATR-based sizing, the hard 1% stop, and the correlation filter.

Sizing keeps *risk* constant rather than notional: a quiet day on gold gets
a bigger position than a volatile day on bitcoin, because size is inversely
proportional to ATR. If the stop is hit, the loss is `risk_per_trade` of
equity — the same 1% for every instrument, every day.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Instrument, RiskConfig
from .strategies.base import LONG


@dataclass(frozen=True)
class PositionPlan:
    quantity: float        # units of the instrument (fractional allowed)
    stop_price: float      # hard stop — exit immediately if touched
    risk_amount: float     # account currency at risk if the stop fills


def plan_position(
    equity: float,
    price: float,
    atr_value: float,
    direction: int,
    cfg: RiskConfig,
) -> PositionPlan | None:
    """Size so that (entry - stop) * quantity == risk_per_trade * equity."""
    if price <= 0 or atr_value <= 0 or equity <= 0:
        return None
    stop_distance = cfg.atr_stop_multiple * atr_value
    risk_amount = cfg.risk_per_trade * equity
    quantity = risk_amount / stop_distance
    # Tight stops on quiet instruments imply huge notional; cap it at what the
    # account can actually carry. Risk at the stop then comes in *under* 1%.
    max_quantity = cfg.max_position_leverage * equity / price
    if quantity > max_quantity:
        quantity = max_quantity
        risk_amount = quantity * stop_distance
    if direction == LONG:
        stop_price = price - stop_distance
    else:
        stop_price = price + stop_distance
    if stop_price <= 0:
        return None
    return PositionPlan(quantity=quantity, stop_price=stop_price, risk_amount=risk_amount)


def correlation_filter_allows(
    instrument: Instrument,
    direction: int,
    open_positions: dict[str, int],
    instruments: dict[str, Instrument],
    cfg: RiskConfig,
) -> tuple[bool, str]:
    """Block a new entry that would concentrate same-direction exposure in
    one risk group. If S&P and NASDAQ are already long, a new bitcoin long
    is the same risk-on bet three times — skip it.

    `open_positions` maps symbol -> direction for currently held positions.
    """
    if len(open_positions) >= cfg.max_open_positions:
        return False, "max open positions reached"

    same_side = sum(
        1
        for sym, held_dir in open_positions.items()
        if held_dir == direction
        and instruments[sym].risk_group == instrument.risk_group
    )
    if same_side >= cfg.max_positions_per_group:
        return False, (
            f"correlation filter: already {same_side} "
            f"{'long' if direction == LONG else 'short'} in '{instrument.risk_group}'"
        )
    return True, "ok"

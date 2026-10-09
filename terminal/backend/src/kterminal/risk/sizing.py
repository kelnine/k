"""Risk-based position sizing (docs/07-risk-engine.md §7.5).

    risk_amount  = equity × risk_pct / 100
    per_unit     = |entry − stop| × point_value × fx(quote → account) + cost_per_unit
    quantity     = floor(risk_amount / per_unit, qty_step)           ← always rounded DOWN

``cost_per_unit`` reserves expected round-trip costs (spread, slippage,
commission) so a full stop-out stays within the budget. Rounding down
guarantees ``actual_risk ≤ risk_amount``; a size below the venue minimum is
rejected rather than rounded up.
"""

from dataclasses import dataclass
from decimal import Decimal

from kterminal.domain.instruments import Listing

HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class SizingResult:
    qty: Decimal
    risk_amount: Decimal  # budget, account currency
    risk_per_unit: Decimal  # account currency per 1.0 quantity, incl. cost reserve
    actual_risk: Decimal  # qty × risk_per_unit
    risk_pct: Decimal  # actual risk as % of equity
    reject_code: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.reject_code is None and self.qty > 0


def size_position(
    *,
    equity: Decimal,
    risk_pct: Decimal,
    entry: Decimal,
    stop: Decimal,
    listing: Listing,
    fx_rate: Decimal = Decimal(1),
    cost_per_unit: Decimal = Decimal(0),
) -> SizingResult:
    if equity <= 0:
        return _reject("NO_EQUITY", "account equity is not positive")
    if risk_pct <= 0:
        return _reject("INVALID_RISK", "risk percentage must be positive")
    distance = abs(entry - stop)
    if distance == 0:
        return _reject("STOP_AT_ENTRY", "stop distance is zero")
    budget = equity * risk_pct / HUNDRED
    per_unit = distance * listing.point_value * fx_rate + max(cost_per_unit, Decimal(0))
    qty = listing.round_qty_down(budget / per_unit)
    if listing.max_qty is not None and qty > listing.max_qty:
        qty = listing.round_qty_down(listing.max_qty)
    if qty < listing.min_qty:
        return SizingResult(
            qty=Decimal(0),
            risk_amount=budget,
            risk_per_unit=per_unit,
            actual_risk=Decimal(0),
            risk_pct=Decimal(0),
            reject_code="SIZE_TOO_SMALL",
            detail=(
                f"risk budget {budget:.2f} buys {budget / per_unit:.6f}, "
                f"below the minimum quantity {listing.min_qty} for {listing.key}"
            ),
        )
    if listing.min_notional is not None:
        notional = listing.notional(qty, entry)  # quote currency, like min_notional
        if notional < listing.min_notional:
            return SizingResult(
                qty=Decimal(0),
                risk_amount=budget,
                risk_per_unit=per_unit,
                actual_risk=Decimal(0),
                risk_pct=Decimal(0),
                reject_code="BELOW_MIN_NOTIONAL",
                detail=f"notional {notional:.2f} below the venue minimum {listing.min_notional}",
            )
    actual = qty * per_unit
    return SizingResult(
        qty=qty,
        risk_amount=budget,
        risk_per_unit=per_unit,
        actual_risk=actual,
        risk_pct=actual / equity * HUNDRED,
    )


def _reject(code: str, detail: str) -> SizingResult:
    zero = Decimal(0)
    return SizingResult(zero, zero, zero, zero, zero, reject_code=code, detail=detail)

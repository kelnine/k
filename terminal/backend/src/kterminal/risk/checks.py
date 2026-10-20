"""Pre-trade checks used by lab paper accounts in Phase 2.

These are the account-independent basics every order must pass. Each check
returns a :class:`RuleResult`; a decision records the result of **every**
check (not just the first failure) so the audit trail shows the full
picture. Phase 5 replaces this list with the complete rule pipeline (daily
loss, static/trailing drawdown, sessions, kill switch …) using the same
result shape.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule: str
    passed: bool
    code: str | None = None
    message: str = ""
    values: dict[str, Any] = field(default_factory=dict)

    def document(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "passed": self.passed,
            "code": self.code,
            "message": self.message,
            "values": {k: str(v) if isinstance(v, Decimal) else v for k, v in self.values.items()},
        }


def passed(rule: str, message: str = "", **values: Any) -> RuleResult:
    return RuleResult(rule, True, None, message, values)


def failed(rule: str, code: str, message: str, **values: Any) -> RuleResult:
    return RuleResult(rule, False, code, message, values)


def first_failure(results: list[RuleResult]) -> RuleResult | None:
    return next((r for r in results if not r.passed), None)


def check_max_open_positions(open_positions: int, limit: int) -> RuleResult:
    if open_positions >= limit:
        return failed(
            "max_open_positions",
            "MAX_POSITIONS",
            f"{open_positions} open/pending positions, limit {limit}",
            open=open_positions,
            limit=limit,
        )
    return passed("max_open_positions", open=open_positions, limit=limit)


def check_stop_not_widened(
    *, is_long: bool, current_stop: Decimal, new_stop: Decimal, allow_widening: bool = False
) -> RuleResult:
    widened = new_stop < current_stop if is_long else new_stop > current_stop
    if widened and not allow_widening:
        return failed(
            "stop_not_widened",
            "STOP_WIDENING_NOT_ALLOWED",
            f"moving the stop from {current_stop} to {new_stop} would increase risk",
            current_stop=current_stop,
            new_stop=new_stop,
        )
    return passed("stop_not_widened", current_stop=current_stop, new_stop=new_stop)

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from kterminal.core.enums import OrderType, SignalAction
from kterminal.domain.signals import (
    InvalidSignalError,
    Signal,
    signal_from_payload,
    validate_signal,
)

T0 = datetime(2026, 10, 5, 14, 35, tzinfo=UTC)


def make(**overrides: Any) -> Signal:
    fields: dict[str, Any] = {
        "strategy_id": "breakout_retest",
        "strategy_version": "abc",
        "symbol": "XAUUSD",
        "timeframe": "5",
        "timestamp": T0,
        "signal": SignalAction.LONG,
        "entry": Decimal("2678.40"),
        "stop_loss": Decimal("2673.20"),
        "take_profit": Decimal("2704.40"),
    }
    fields.update(overrides)
    return Signal(**fields)


def test_standard_fields_and_normalisation() -> None:
    signal = validate_signal(make(risk=Decimal("0.5"), confidence=0.8, metadata={"level": 1}))
    assert signal.timeframe == "5m"
    assert signal.reward_risk == Decimal(5)
    dumped = signal.model_dump(mode="json")
    for key in (
        "strategy_id",
        "symbol",
        "timeframe",
        "timestamp",
        "signal",
        "entry",
        "stop_loss",
        "take_profit",
        "risk",
        "confidence",
        "metadata",
    ):
        assert key in dumped


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"entry": None}, "ENTRY_REQUIRED"),
        ({"stop_loss": None}, "STOP_REQUIRED"),
        ({"stop_loss": Decimal("2680")}, "STOP_WRONG_SIDE"),
        ({"take_profit": Decimal("2670")}, "TARGET_WRONG_SIDE"),
        ({"signal": SignalAction.SHORT}, "STOP_WRONG_SIDE"),
        ({"signal": SignalAction.SHORT, "stop_loss": Decimal("2690")}, "TARGET_WRONG_SIDE"),
        ({"signal": SignalAction.EXIT_LONG}, "PRICES_NOT_ALLOWED"),
        ({"signal": SignalAction.MOVE_SL, "stop_loss": None}, "STOP_REQUIRED"),
        ({"signal": SignalAction.NO_TRADE}, "PRICES_NOT_ALLOWED"),
        ({"risk": Decimal(0)}, "INVALID_RISK"),
        ({"risk": Decimal(101)}, "INVALID_RISK"),
        ({"confidence": 1.5}, "INVALID_CONFIDENCE"),
        ({"expires_after_bars": 3}, "EXPIRY_NOT_APPLICABLE"),
        ({"order_type": OrderType.LIMIT, "expires_after_bars": 0}, "INVALID_EXPIRY"),
        ({"metadata": {"blob": "x" * 20_000}}, "METADATA_TOO_LARGE"),
    ],
)
def test_rule_violations(overrides: dict[str, Any], code: str) -> None:
    with pytest.raises(InvalidSignalError) as excinfo:
        validate_signal(make(**overrides))
    assert excinfo.value.code == code


def test_valid_non_entry_actions() -> None:
    validate_signal(make(signal=SignalAction.EXIT_LONG, stop_loss=None, take_profit=None))
    validate_signal(make(signal=SignalAction.MOVE_SL, entry=None, take_profit=None))
    validate_signal(
        make(
            signal=SignalAction.NO_TRADE,
            entry=None,
            stop_loss=None,
            take_profit=None,
            reason="outside session",
        )
    )
    exit_with_limit = make(
        signal=SignalAction.EXIT_SHORT, stop_loss=None, take_profit=None, order_type=OrderType.LIMIT
    )
    with pytest.raises(InvalidSignalError, match="always a market action"):
        validate_signal(exit_with_limit)


def test_model_level_validation() -> None:
    with pytest.raises(ValidationError, match="positive"):
        make(entry=Decimal("-1"))
    with pytest.raises(ValidationError, match="naive"):
        make(timestamp=datetime(2026, 1, 1))  # noqa: DTZ001
    with pytest.raises(ValidationError):
        make(unknown_field=1)
    with pytest.raises(ValidationError):
        make().signal = SignalAction.SHORT  # type: ignore[misc]


def test_signal_from_payload() -> None:
    payload = make().model_dump(mode="json")
    assert signal_from_payload(payload) == make()

"""The standardized strategy output.

Every strategy — a Python plug-in or a TradingView script arriving by webhook
— produces the same :class:`Signal`. The fields required by the brief are
``strategy_id, symbol, timeframe, timestamp, signal, entry, stop_loss,
take_profit, risk, confidence, metadata``. The framework additionally stamps
``strategy_version`` (the immutable version of the code *and* configuration
that produced the signal), so later edits can never blur historical
comparisons.

Semantic rules (enforced by :func:`validate_signal`):

=============  ========  ==========  ===========  =========================================
signal         entry     stop_loss   take_profit  rules
=============  ========  ==========  ===========  =========================================
LONG           required  required    optional     stop < entry < take_profit
SHORT          required  required    optional     take_profit < entry < stop
EXIT_LONG/…    optional  —           —            closes this strategy's position
MOVE_SL        optional  required    optional     new stop (and optionally new target)
NO_TRADE       —         —           —            ``reason`` recommended
=============  ========  ==========  ===========  =========================================
"""

import json
import math
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from kterminal.core.clock import ensure_utc
from kterminal.core.enums import OrderType, SignalAction, SignalSource
from kterminal.domain.timeframes import Timeframe

MAX_METADATA_BYTES = 16_384
# What the system of record can hold exactly (PostgreSQL numeric(24,10) prices and
# numeric(8,4) risk). A signal outside these limits is refused for its own instance
# instead of failing a whole lab write for everyone.
MAX_PRICE = Decimal("1e14")
PRICE_DECIMALS = 10
RISK_DECIMALS = 4


class InvalidSignalError(ValueError):
    """A signal violates the standard. ``code`` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # ── the standardized output ─────────────────────────────────────────────
    strategy_id: str = Field(description="Strategy instance id (the unit every metric is keyed on)")
    symbol: str = Field(description="Canonical instrument symbol, e.g. XAUUSD, MNQ, NEARUSD")
    timeframe: str = Field(description="Canonical timeframe of the bar evaluated, e.g. 5m")
    timestamp: datetime = Field(description="Decision time (UTC): close time of the evaluated bar")
    signal: SignalAction
    entry: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    risk: Decimal | None = Field(default=None, description="Requested risk, % of equity")
    confidence: float | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    # ── framework-stamped identity & options ────────────────────────────────
    strategy_version: str = Field(description="Immutable version id of code + configuration")
    bar_time: datetime | None = Field(default=None, description="Open time of the evaluated bar")
    source: SignalSource = SignalSource.INTERNAL
    order_type: OrderType = OrderType.MARKET
    expires_after_bars: int | None = None
    reason: str | None = None
    persist: bool = False  # persist a NO_TRADE (they are otherwise only counted)

    @field_validator("timestamp", "bar_time")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @field_validator("timeframe")
    @classmethod
    def _canonical_timeframe(cls, value: str) -> str:
        return Timeframe.parse(value).code

    @field_validator("entry", "stop_loss", "take_profit")
    @classmethod
    def _positive_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value <= 0):
            raise ValueError("prices must be positive, finite numbers")
        return value

    @property
    def tf(self) -> Timeframe:
        return Timeframe.parse(self.timeframe)

    @property
    def reward_risk(self) -> Decimal | None:
        """|target − entry| / |entry − stop| for entries with all three prices."""
        if self.entry is None or self.stop_loss is None or self.take_profit is None:
            return None
        risk = abs(self.entry - self.stop_loss)
        return abs(self.take_profit - self.entry) / risk if risk else None


def validate_signal(signal: Signal) -> Signal:
    """Check the per-action rules; raise :class:`InvalidSignalError` on the first violation."""
    action = signal.signal
    entry, stop, target = signal.entry, signal.stop_loss, signal.take_profit

    if action.is_entry:
        if entry is None:
            raise InvalidSignalError("ENTRY_REQUIRED", f"{action} requires an entry price")
        if stop is None:
            raise InvalidSignalError("STOP_REQUIRED", f"{action} requires a stop_loss")
        if action is SignalAction.LONG:
            if not stop < entry:
                raise InvalidSignalError("STOP_WRONG_SIDE", "LONG stop_loss must be below entry")
            if target is not None and not target > entry:
                raise InvalidSignalError(
                    "TARGET_WRONG_SIDE", "LONG take_profit must be above entry"
                )
        else:
            if not stop > entry:
                raise InvalidSignalError("STOP_WRONG_SIDE", "SHORT stop_loss must be above entry")
            if target is not None and not target < entry:
                raise InvalidSignalError(
                    "TARGET_WRONG_SIDE", "SHORT take_profit must be below entry"
                )
        if signal.expires_after_bars is not None:
            if signal.order_type is OrderType.MARKET:
                raise InvalidSignalError("EXPIRY_NOT_APPLICABLE", "market entries cannot expire")
            if signal.expires_after_bars < 1:
                raise InvalidSignalError("INVALID_EXPIRY", "expires_after_bars must be >= 1")
    elif action.is_exit:
        if stop is not None or target is not None:
            raise InvalidSignalError("PRICES_NOT_ALLOWED", f"{action} takes no stop/target")
    elif action is SignalAction.MOVE_SL:
        if stop is None:
            raise InvalidSignalError("STOP_REQUIRED", "MOVE_SL requires the new stop_loss")
    elif action is SignalAction.NO_TRADE and any(v is not None for v in (entry, stop, target)):
        raise InvalidSignalError("PRICES_NOT_ALLOWED", "NO_TRADE takes no prices")

    if not action.is_entry and signal.order_type is not OrderType.MARKET:
        raise InvalidSignalError("ORDER_TYPE_NOT_APPLICABLE", f"{action} is always a market action")
    for name, price in (("entry", entry), ("stop_loss", stop), ("take_profit", target)):
        if price is None:
            continue
        if not (isinstance(price, Decimal) and price.is_finite() and 0 < price < MAX_PRICE):
            raise InvalidSignalError("INVALID_PRICE", f"{name} must be in (0, {MAX_PRICE:,f})")
        if _decimals(price) > PRICE_DECIMALS:
            raise InvalidSignalError(
                "INVALID_PRICE", f"{name} has more than {PRICE_DECIMALS} decimal places"
            )
    risk = signal.risk
    if risk is not None and not (
        isinstance(risk, Decimal) and risk.is_finite() and Decimal(0) < risk <= Decimal(100)
    ):
        raise InvalidSignalError("INVALID_RISK", "risk must be a percentage in (0, 100]")
    if risk is not None and _decimals(risk) > RISK_DECIMALS:
        raise InvalidSignalError(
            "INVALID_RISK", f"risk has more than {RISK_DECIMALS} decimal places (e.g. 0.25)"
        )
    confidence = signal.confidence
    if confidence is not None and not (
        isinstance(confidence, (int, float))
        and math.isfinite(confidence)
        and 0.0 <= confidence <= 1.0
    ):
        raise InvalidSignalError("INVALID_CONFIDENCE", "confidence must be within [0, 1]")
    try:
        # Strict JSON: no NaN/Infinity and no non-JSON objects (they could not be stored).
        size = len(json.dumps(signal.metadata, allow_nan=False).encode())
    except (TypeError, ValueError) as exc:
        raise InvalidSignalError(
            "METADATA_NOT_JSON", f"metadata must be plain JSON (no NaN/Infinity): {exc}"
        ) from None
    if size > MAX_METADATA_BYTES:
        raise InvalidSignalError("METADATA_TOO_LARGE", f"metadata is {size} bytes (max 16 KiB)")
    if _has_nul(signal.metadata) or _has_nul(signal.reason):
        raise InvalidSignalError(
            "NUL_CHARACTER", "metadata and reason must not contain NUL (\\x00) characters"
        )
    return signal


def _decimals(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _has_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_has_nul(v) for v in value)
    return False


def signal_from_payload(payload: dict[str, Any]) -> Signal:
    """Build and validate a signal from plain data (webhook mapping, replay, IPC)."""
    return validate_signal(Signal.model_validate(payload))

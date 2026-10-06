"""Transaction costs: spread, commission, slippage, funding and swap.

The strategy lab compares strategies by their *net* results, so the costs the
paper/backtest simulator charges must be explicit, exact and identical for
every account that shares a venue profile. This module is the single place
those costs are defined (docs/11-instruments-sessions-costs.md §11.4):

* **Configuration, not code.** Each listing points at a :class:`CostProfile`
  loaded from ``terminal/config/catalog/costs.yaml``. A profile is five
  independent components — spread, commission, slippage, funding, swap — each
  with a small set of models selected by a ``model`` discriminator, so changing
  an assumption never means changing code (and changes the catalog
  fingerprint, so historical trades keep the costs they were made with).
* **Exact and deterministic.** Everything is ``Decimal``; floats are rejected
  even when parsing YAML (write decimals as quoted strings). The same inputs
  always produce the same fills and amounts: the calculator does its
  arithmetic in a private decimal context, so a strategy or library that
  changes the thread's ambient context (precision, rounding) cannot change
  what any lab account is charged.
* **Never flattering.** Market and stop fills cross half the spread and pay
  slippage, then round to the listing's tick *adversely* (buys up, sells down).
  Limit orders (targets) fill exactly at their price but trigger only when the
  far side of the spread reaches them. Fees round up; funding and swap cash
  flows round towards −∞. All rounding is to :data:`MONEY_QUANTUM`.
* **Attributable.** Spread, slippage, commission, funding and swap are returned
  separately (:class:`FillPrice` breaks a fill down) so analytics can report
  each cost per strategy.

Sign conventions: commissions are non-negative fees; funding and swap are
signed cash flows *to the account* (negative = the account pays). All money is
in the listing's quote currency.

Time: every instant is timezone-aware UTC; swap rollovers are local times in an
IANA zone evaluated with ``zoneinfo``, so daylight-saving changes move the UTC
instant while the local rollover time (e.g. 17:00 New York) stays put.
"""

import functools
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from enum import StrEnum
from typing import Any, ClassVar, Self, assert_never
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kterminal.core.clock import ensure_utc
from kterminal.core.enums import Direction, OrderSide
from kterminal.domain.instruments import ID_PATTERN, ContractType, Listing
from kterminal.domain.market import Quote

#: Money amounts (fees, funding, swap) are quantized to this step, adversely.
MONEY_QUANTUM = Decimal("0.0001")
#: Weekday names used in documents; index = ``date.weekday()`` (Monday = 0).
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
_WEEKDAY_NAMES = {name: index for index, name in enumerate(WEEKDAYS)} | {
    full: index
    for index, full in enumerate(
        ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
    )
}
#: Upper bound (exclusive) for fractional rates — catches "0.05 meaning 0.05 %" typos.
MAX_RATE = Decimal("0.05")
#: Upper bound (exclusive) for slippage in basis points.
MAX_BPS = Decimal(1_000)
_BPS = Decimal(10_000)
_ZERO = Decimal(0)
_COMPONENTS = ("spread", "commission", "slippage", "funding", "swap")
#: Local times in documents: exactly "HH:MM" or "HH:MM:SS". ``time.fromisoformat``
#: alone is too lenient — it reads "17.30" as 17:00:00.3, not 17:30.
_TIME_PATTERN = re.compile(r"([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?")
#: The calculator's private arithmetic context: wide enough to be exact for any
#: realistic price × quantity × rate, independent of the thread's ambient
#: context, and trapping anything that would silently produce NaN or infinity.
_CONTEXT = Context(
    prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow]
)

type PriceSource = Decimal | Callable[[datetime], Decimal]
"""A fixed price, or a function returning the price at an instant (e.g. a mark-price series)."""


class CostConfigError(ValueError):
    """A cost profile or cost model is invalid."""


class Liquidity(StrEnum):
    """Whether a fill added liquidity (resting limit order) or took it (market/stop)."""

    MAKER = "MAKER"
    TAKER = "TAKER"


class CostEventKind(StrEnum):
    """Ledger kinds of time-based costs (they match the account ledger's ``kind``)."""

    FUNDING = "FUNDING"
    SWAP = "SWAP"


# ── parsing / validation helpers ─────────────────────────────────────────────
def _fields(
    data: object, model: str, required: tuple[str, ...] = (), optional: tuple[str, ...] = ()
) -> Mapping[str, Any]:
    """Check a model document: right discriminator, no unknown or missing keys."""
    if not isinstance(data, Mapping):
        raise CostConfigError(f"expected a mapping with a 'model' key, got {type(data).__name__}")
    if data.get("model") != model:
        raise CostConfigError(f"expected model {model!r}, got {data.get('model')!r}")
    allowed = {"model", *required, *optional}
    unknown = sorted(str(key) for key in data if key not in allowed)
    if unknown:
        raise CostConfigError(
            f"model {model!r}: unknown field(s) {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(allowed - {'model'})) or '(none)'}"
        )
    missing = [key for key in required if key not in data]
    if missing:
        raise CostConfigError(f"model {model!r}: missing field(s) {', '.join(missing)}")
    return data


def _to_decimal(value: object, field: str) -> Decimal:
    """Parse a document decimal. Strings and ints only: floats would carry binary noise."""
    if isinstance(value, bool):
        raise CostConfigError(f"{field}: expected a decimal, got the boolean {value!r}")
    if isinstance(value, float):
        raise CostConfigError(
            f'{field}: write decimals as quoted strings (e.g. "0.20"), not the float {value!r}, '
            "so no binary rounding creeps into the costs"
        )
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation:
            raise CostConfigError(f"{field}: {value!r} is not a decimal number") from None
    else:
        raise CostConfigError(f"{field}: expected a decimal string, got {type(value).__name__}")
    if not result.is_finite():
        raise CostConfigError(f"{field}: {value!r} is not a finite number")
    return result


def _to_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CostConfigError(f"{field}: expected an integer, got {value!r}")
    return value


def _to_weekday(value: object, field: str) -> int:
    """``WED`` / ``Wednesday`` / ``2`` → 2 (Monday = 0, like ``date.weekday()``)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().upper() in _WEEKDAY_NAMES:
        return _WEEKDAY_NAMES[value.strip().upper()]
    raise CostConfigError(f"{field}: expected a weekday (MON … SUN or 0-6), got {value!r}")


def _to_time(value: object, field: str) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        raise CostConfigError(
            f'{field}: quote local times, e.g. "17:00" — YAML 1.1 reads an unquoted 17:00 as '
            f"the number {17 * 60}, and got {value!r}"
        )
    match = _TIME_PATTERN.fullmatch(value.strip()) if isinstance(value, str) else None
    if match is not None:
        hour, minute, second = match.groups()
        try:
            return time(int(hour), int(minute), int(second or 0))
        except ValueError:
            pass
    raise CostConfigError(f'{field}: expected a local time "HH:MM" or "HH:MM:SS", got {value!r}')


def _format_time(value: time) -> str:
    text = f"{value.hour:02d}:{value.minute:02d}"
    return f"{text}:{value.second:02d}" if value.second else text


def _check_decimal(
    where: str,
    value: object,
    *,
    non_negative: bool = False,
    abs_below: Decimal | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise CostConfigError(f"{where} must be a Decimal, got {type(value).__name__} {value!r}")
    if not value.is_finite():
        raise CostConfigError(f"{where} must be finite, got {value}")
    if non_negative and value < 0:
        raise CostConfigError(f"{where} cannot be negative, got {value}")
    if abs_below is not None and value.copy_abs() >= abs_below:  # copy_abs: context-free
        raise CostConfigError(
            f"{where} {value} is implausibly large (|value| must be below {abs_below}); "
            "rates are fractions, e.g. 0.0005 = 0.05 %"
        )


def _check_int(where: str, value: object, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CostConfigError(f"{where} must be an integer in [{low}, {high}], got {value!r}")


def _zone(name: object, where: str) -> ZoneInfo:
    if not isinstance(name, str) or not name:
        raise CostConfigError(f"{where}: expected an IANA time zone name, got {name!r}")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise CostConfigError(f"{where}: unknown time zone {name!r}") from None


def _check_rollover(
    where: str, rollover_time: object, timezone: object, triple_day: object
) -> None:
    if not isinstance(rollover_time, time):
        raise CostConfigError(f"{where} rollover_time must be a datetime.time")
    if rollover_time.tzinfo is not None:
        raise CostConfigError(f"{where} rollover_time must be a local time (zone is 'timezone')")
    if rollover_time.microsecond:
        raise CostConfigError(
            f"{where} rollover_time must be whole seconds (HH:MM[:SS]), got {rollover_time}"
        )
    _zone(timezone, f"{where} timezone")
    _check_int(f"{where} triple_day", triple_day, 0, 4)  # Sat/Sun rollovers are skipped


def _require_positive(value: object, name: str) -> Decimal:
    """Runtime guard as well as a type check: floats must never reach cost maths."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a positive, finite number, got {value}")
    return value


def _fee(amount: Decimal) -> Decimal:
    """A non-negative fee, rounded *up* so rounding never flatters the account."""
    return amount.quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)


def _cash_flow(amount: Decimal) -> Decimal:
    """A signed cash flow to the account, rounded towards −∞ (never flattering)."""
    result = amount.quantize(MONEY_QUANTUM, rounding=ROUND_FLOOR)
    return result if result else abs(result)  # normalise -0.0000


def _exact[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """Run ``method`` in :data:`_CONTEXT`, whatever the caller's decimal context is."""

    @functools.wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with localcontext(_CONTEXT):
            return method(*args, **kwargs)

    return wrapper


def _price_at(source: PriceSource, at: datetime, name: str) -> Decimal:
    price = source if isinstance(source, Decimal) else source(at)
    return _require_positive(price, f"{name} at {at.isoformat()}")


# ── spread models ────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class NoSpread:
    """Frictionless: buys and sells fill at the mid (for zero-cost comparisons)."""

    model: ClassVar[str] = "none"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model)
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model}


@dataclass(frozen=True, slots=True)
class FixedSpread:
    """A constant full spread in price units (gold 0.20 = 20 cents)."""

    points: Decimal
    model: ClassVar[str] = "fixed"

    def __post_init__(self) -> None:
        _check_decimal("fixed spread points", self.points, non_negative=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("points",))
        return cls(points=_to_decimal(data["points"], "points"))

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "points": str(self.points)}


@dataclass(frozen=True, slots=True)
class FixedTicksSpread:
    """A constant full spread in ticks of the listing (MNQ: 1 tick = 0.25)."""

    ticks: int
    model: ClassVar[str] = "fixed_ticks"

    def __post_init__(self) -> None:
        _check_int("fixed_ticks spread ticks", self.ticks, 0, 1_000_000)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("ticks",))
        return cls(ticks=_to_int(data["ticks"], "ticks"))

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "ticks": self.ticks}


@dataclass(frozen=True, slots=True)
class SessionSpread:
    """A different full spread per session window (e.g. wider in Asia or at rollover).

    ``by_window`` is ordered: the first window the instant falls into wins;
    outside every listed window ``default_points`` applies.
    """

    default_points: Decimal
    by_window: tuple[tuple[str, Decimal], ...] = ()
    model: ClassVar[str] = "session"

    def __post_init__(self) -> None:
        _check_decimal("session spread default_points", self.default_points, non_negative=True)
        raw: object = self.by_window
        pairs = list(raw.items()) if isinstance(raw, Mapping) else raw
        if isinstance(pairs, str) or not isinstance(pairs, Iterable):
            raise CostConfigError("session spread by_window: expected (window id, points) pairs")
        # Normalised to a tuple of tuples so the model stays hashable and compares by value.
        normalised = tuple(
            tuple(pair) if isinstance(pair, list | tuple) else pair for pair in pairs
        )
        for pair in normalised:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise CostConfigError(
                    f"session spread by_window: expected a (window id, points) pair, got {pair!r}"
                )
        object.__setattr__(self, "by_window", normalised)
        seen: set[str] = set()
        for window_id, points in self.by_window:
            if not isinstance(window_id, str) or not ID_PATTERN.fullmatch(window_id):
                raise CostConfigError(
                    f"session spread: invalid window id {window_id!r} (session window ids are "
                    "lower_snake_case)"
                )
            if window_id in seen:
                raise CostConfigError(f"session spread: window {window_id!r} listed twice")
            seen.add(window_id)
            _check_decimal(f"session spread {window_id!r} points", points, non_negative=True)

    @property
    def window_ids(self) -> frozenset[str]:
        return frozenset(window_id for window_id, _ in self.by_window)

    def points_for(self, active_windows: frozenset[str]) -> Decimal:
        for window_id, points in self.by_window:
            if window_id in active_windows:
                return points
        return self.default_points

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("default_points",), ("by_window",))
        raw = data.get("by_window")
        if raw is None:  # `by_window:` with no value
            raw = {}
        if not isinstance(raw, Mapping):
            raise CostConfigError(
                f"by_window: expected a mapping of window id → points, got {raw!r}"
            )
        return cls(
            default_points=_to_decimal(data["default_points"], "default_points"),
            by_window=tuple(
                (window_id, _to_decimal(points, f"by_window.{window_id}"))
                for window_id, points in raw.items()
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "default_points": str(self.default_points),
            "by_window": {window_id: str(points) for window_id, points in self.by_window},
        }


@dataclass(frozen=True, slots=True)
class QuoteSpread:
    """The real bid/ask from a quote when one is available, else ``fallback_points``."""

    fallback_points: Decimal
    model: ClassVar[str] = "quotes"

    def __post_init__(self) -> None:
        _check_decimal("quotes spread fallback_points", self.fallback_points, non_negative=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("fallback_points",))
        return cls(fallback_points=_to_decimal(data["fallback_points"], "fallback_points"))

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "fallback_points": str(self.fallback_points)}


type SpreadModel = NoSpread | FixedSpread | FixedTicksSpread | SessionSpread | QuoteSpread


# ── commission models ────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class NoCommission:
    model: ClassVar[str] = "none"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model)
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model}


@dataclass(frozen=True, slots=True)
class PerQuantityCommission:
    """A fee per unit of quantity per side: per lot (CFD/FX) or per contract (futures,
    all-in: exchange + clearing + NFA + broker), with an optional minimum per fill."""

    per_side: Decimal
    minimum: Decimal = _ZERO
    model: ClassVar[str] = "per_quantity"

    def __post_init__(self) -> None:
        _check_decimal("per_quantity commission per_side", self.per_side, non_negative=True)
        _check_decimal("per_quantity commission minimum", self.minimum, non_negative=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("per_side",), ("minimum",))
        return cls(
            per_side=_to_decimal(data["per_side"], "per_side"),
            minimum=_to_decimal(data.get("minimum", 0), "minimum"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "per_side": str(self.per_side), "minimum": str(self.minimum)}


@dataclass(frozen=True, slots=True)
class NotionalCommission:
    """A maker/taker rate of the fill's notional (crypto). Rebates (negative maker
    rates) are deliberately not modelled: the conservative assumption is a fee."""

    maker_rate: Decimal
    taker_rate: Decimal
    minimum: Decimal = _ZERO
    model: ClassVar[str] = "notional"

    def __post_init__(self) -> None:
        for name in ("maker_rate", "taker_rate"):
            _check_decimal(
                f"notional commission {name}",
                getattr(self, name),
                non_negative=True,
                abs_below=MAX_RATE,
            )
        _check_decimal("notional commission minimum", self.minimum, non_negative=True)

    def rate(self, liquidity: Liquidity) -> Decimal:
        return self.maker_rate if liquidity is Liquidity.MAKER else self.taker_rate

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("maker_rate", "taker_rate"), ("minimum",))
        return cls(
            maker_rate=_to_decimal(data["maker_rate"], "maker_rate"),
            taker_rate=_to_decimal(data["taker_rate"], "taker_rate"),
            minimum=_to_decimal(data.get("minimum", 0), "minimum"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "maker_rate": str(self.maker_rate),
            "taker_rate": str(self.taker_rate),
            "minimum": str(self.minimum),
        }


type CommissionModel = NoCommission | PerQuantityCommission | NotionalCommission


# ── slippage models ──────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class NoSlippage:
    model: ClassVar[str] = "none"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model)
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model}


@dataclass(frozen=True, slots=True)
class FixedTicksSlippage:
    """Adverse slippage of a fixed number of the listing's ticks on market/stop fills."""

    ticks: int
    model: ClassVar[str] = "fixed_ticks"

    def __post_init__(self) -> None:
        _check_int("fixed_ticks slippage ticks", self.ticks, 0, 1_000_000)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("ticks",))
        return cls(ticks=_to_int(data["ticks"], "ticks"))

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "ticks": self.ticks}


@dataclass(frozen=True, slots=True)
class NotionalBpsSlippage:
    """Adverse slippage proportional to price, in basis points (1 bp = 0.01 %)."""

    bps: Decimal
    model: ClassVar[str] = "notional_bps"

    def __post_init__(self) -> None:
        _check_decimal("notional_bps slippage bps", self.bps, non_negative=True, abs_below=MAX_BPS)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("bps",))
        return cls(bps=_to_decimal(data["bps"], "bps"))

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "bps": str(self.bps)}


type SlippageModel = NoSlippage | FixedTicksSlippage | NotionalBpsSlippage


# ── funding models (perpetuals) ──────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class NoFunding:
    model: ClassVar[str] = "none"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model)
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model}


@dataclass(frozen=True, slots=True)
class ConstantFunding:
    """A constant funding rate charged at fixed UTC instants.

    A positive rate means longs pay shorts. ``anchor_hours_utc`` lists the
    funding hours of every UTC day (e.g. 0, 8, 16); when empty, funding is
    every ``interval_hours`` from 00:00 UTC (``interval_hours: 1`` = hourly).
    """

    rate_per_interval: Decimal
    interval_hours: int
    anchor_hours_utc: tuple[int, ...] = ()
    model: ClassVar[str] = "constant"

    def __post_init__(self) -> None:
        _check_decimal(
            "constant funding rate_per_interval", self.rate_per_interval, abs_below=MAX_RATE
        )
        _check_int("constant funding interval_hours", self.interval_hours, 1, 24)
        if 24 % self.interval_hours:
            raise CostConfigError(
                f"constant funding interval_hours must divide 24, got {self.interval_hours}"
            )
        if not isinstance(self.anchor_hours_utc, list | tuple):
            raise CostConfigError(
                f"constant funding anchor_hours_utc must be a sequence of UTC hours, "
                f"got {self.anchor_hours_utc!r}"
            )
        # Normalised to a tuple so the model stays hashable and compares by value.
        object.__setattr__(self, "anchor_hours_utc", tuple(self.anchor_hours_utc))
        anchors = self.anchor_hours_utc
        for hour in anchors:
            _check_int("constant funding anchor hour", hour, 0, 23)
        if list(anchors) != sorted(set(anchors)):
            raise CostConfigError(
                f"constant funding anchor_hours_utc must be unique and ascending, got {anchors}"
            )
        if anchors:
            # A single anchor wraps onto itself: its gap is a whole day, not 0.
            gaps = [
                (b - a) % 24 or 24 for a, b in zip(anchors, (*anchors[1:], anchors[0]), strict=True)
            ]
            if len(anchors) != 24 // self.interval_hours or any(
                gap != self.interval_hours for gap in gaps
            ):
                raise CostConfigError(
                    f"constant funding anchor_hours_utc {list(anchors)} are not every "
                    f"{self.interval_hours} h; fix the anchors or interval_hours"
                )

    @property
    def anchor_hours(self) -> tuple[int, ...]:
        """The UTC hours of each day at which funding is exchanged."""
        return self.anchor_hours_utc or tuple(range(0, 24, self.interval_hours))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("rate_per_interval", "interval_hours"), ("anchor_hours_utc",))
        raw = data.get("anchor_hours_utc")
        if raw is None:  # `anchor_hours_utc:` with no value
            raw = []
        if not isinstance(raw, list | tuple):
            raise CostConfigError(f"anchor_hours_utc: expected a list of UTC hours, got {raw!r}")
        return cls(
            rate_per_interval=_to_decimal(data["rate_per_interval"], "rate_per_interval"),
            interval_hours=_to_int(data["interval_hours"], "interval_hours"),
            anchor_hours_utc=tuple(sorted(_to_int(h, "anchor_hours_utc") for h in raw)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "rate_per_interval": str(self.rate_per_interval),
            "interval_hours": self.interval_hours,
            "anchor_hours_utc": list(self.anchor_hours_utc),
        }


type FundingModel = NoFunding | ConstantFunding


# ── swap / overnight financing models (CFD, FX) ──────────────────────────────
@dataclass(frozen=True, slots=True)
class NoSwap:
    model: ClassVar[str] = "none"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model)
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model}


_ROLLOVER_FIELDS = ("rollover_time", "timezone", "triple_day")


@dataclass(frozen=True, slots=True)
class PointsSwap:
    """Swap in price points per 1.0 quantity per night, *signed as given*
    (negative = the account is charged): amount = points × contract_size × qty.

    ``rollover_time``/``timezone`` are the end of the trading day (17:00 New
    York for FX/CFDs — "server midnight" on NY-close MT5 servers), so the local
    weekday of a rollover is the trading day it ends; Saturday and Sunday
    rollovers are skipped and the ``triple_day`` rollover counts three nights.
    MT5 quotes swaps in *points* of the symbol's digits: convert to price units
    (e.g. −65 points on a 2-digit gold symbol = −0.65).
    """

    long_points: Decimal
    short_points: Decimal
    rollover_time: time
    timezone: str
    triple_day: int
    model: ClassVar[str] = "points"

    def __post_init__(self) -> None:
        _check_decimal("points swap long_points", self.long_points)
        _check_decimal("points swap short_points", self.short_points)
        _check_rollover("points swap", self.rollover_time, self.timezone, self.triple_day)

    def points(self, direction: Direction) -> Decimal:
        return self.long_points if direction is Direction.LONG else self.short_points

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("long_points", "short_points", *_ROLLOVER_FIELDS))
        return cls(
            long_points=_to_decimal(data["long_points"], "long_points"),
            short_points=_to_decimal(data["short_points"], "short_points"),
            rollover_time=_to_time(data["rollover_time"], "rollover_time"),
            timezone=data["timezone"],
            triple_day=_to_weekday(data["triple_day"], "triple_day"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "long_points": str(self.long_points),
            "short_points": str(self.short_points),
            "rollover_time": _format_time(self.rollover_time),
            "timezone": self.timezone,
            "triple_day": WEEKDAYS[self.triple_day],
        }


@dataclass(frozen=True, slots=True)
class AnnualRateSwap:
    """Overnight financing as an annual rate of notional. A *positive* rate means
    the account pays: amount per night = −rate × notional / day_count.

    Rollover rules are those of :class:`PointsSwap`.
    """

    long_rate: Decimal
    short_rate: Decimal
    rollover_time: time
    timezone: str
    triple_day: int
    day_count: int = 365
    model: ClassVar[str] = "annual_rate"

    def __post_init__(self) -> None:
        _check_decimal("annual_rate swap long_rate", self.long_rate, abs_below=Decimal(1))
        _check_decimal("annual_rate swap short_rate", self.short_rate, abs_below=Decimal(1))
        _check_rollover("annual_rate swap", self.rollover_time, self.timezone, self.triple_day)
        if self.day_count not in (360, 365):
            raise CostConfigError(
                f"annual_rate swap day_count must be 360 or 365, got {self.day_count!r}"
            )

    def rate(self, direction: Direction) -> Decimal:
        return self.long_rate if direction is Direction.LONG else self.short_rate

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        _fields(data, cls.model, ("long_rate", "short_rate", *_ROLLOVER_FIELDS), ("day_count",))
        return cls(
            long_rate=_to_decimal(data["long_rate"], "long_rate"),
            short_rate=_to_decimal(data["short_rate"], "short_rate"),
            rollover_time=_to_time(data["rollover_time"], "rollover_time"),
            timezone=data["timezone"],
            triple_day=_to_weekday(data["triple_day"], "triple_day"),
            day_count=_to_int(data.get("day_count", 365), "day_count"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "long_rate": str(self.long_rate),
            "short_rate": str(self.short_rate),
            "rollover_time": _format_time(self.rollover_time),
            "timezone": self.timezone,
            "triple_day": WEEKDAYS[self.triple_day],
            "day_count": self.day_count,
        }


type SwapModel = NoSwap | PointsSwap | AnnualRateSwap

type _Parser[T] = Callable[[Mapping[str, Any]], T]

_SPREAD_PARSERS: Mapping[str, _Parser[SpreadModel]] = {
    NoSpread.model: NoSpread.from_dict,
    FixedSpread.model: FixedSpread.from_dict,
    FixedTicksSpread.model: FixedTicksSpread.from_dict,
    SessionSpread.model: SessionSpread.from_dict,
    QuoteSpread.model: QuoteSpread.from_dict,
}
_COMMISSION_PARSERS: Mapping[str, _Parser[CommissionModel]] = {
    NoCommission.model: NoCommission.from_dict,
    PerQuantityCommission.model: PerQuantityCommission.from_dict,
    NotionalCommission.model: NotionalCommission.from_dict,
}
_SLIPPAGE_PARSERS: Mapping[str, _Parser[SlippageModel]] = {
    NoSlippage.model: NoSlippage.from_dict,
    FixedTicksSlippage.model: FixedTicksSlippage.from_dict,
    NotionalBpsSlippage.model: NotionalBpsSlippage.from_dict,
}
_FUNDING_PARSERS: Mapping[str, _Parser[FundingModel]] = {
    NoFunding.model: NoFunding.from_dict,
    ConstantFunding.model: ConstantFunding.from_dict,
}
_SWAP_PARSERS: Mapping[str, _Parser[SwapModel]] = {
    NoSwap.model: NoSwap.from_dict,
    PointsSwap.model: PointsSwap.from_dict,
    AnnualRateSwap.model: AnnualRateSwap.from_dict,
}


_COMPONENT_TYPES: Mapping[str, tuple[type, ...]] = {
    "spread": (NoSpread, FixedSpread, FixedTicksSpread, SessionSpread, QuoteSpread),
    "commission": (NoCommission, PerQuantityCommission, NotionalCommission),
    "slippage": (NoSlippage, FixedTicksSlippage, NotionalBpsSlippage),
    "funding": (NoFunding, ConstantFunding),
    "swap": (NoSwap, PointsSwap, AnnualRateSwap),
}


def _parse_component[T](data: object, parsers: Mapping[str, _Parser[T]], component: str) -> T:
    if not isinstance(data, Mapping):
        raise CostConfigError(
            f"{component}: expected a mapping such as {{model: none}}, got {type(data).__name__}"
        )
    model = data.get("model")
    if not isinstance(model, str) or model not in parsers:
        raise CostConfigError(
            f"{component}: unknown model {model!r}; expected one of {', '.join(parsers)}"
        )
    try:
        return parsers[model](data)
    except CostConfigError as exc:
        raise CostConfigError(f"{component}: {exc}") from exc


# ── profiles ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class CostProfile:
    """The five independent cost components a listing is simulated with.

    Every component is required in documents — use ``{model: none}`` to say
    "no cost" explicitly — so a forgotten commission can never silently turn
    into a free one.
    """

    id: str
    description: str
    spread: SpreadModel
    commission: CommissionModel
    slippage: SlippageModel
    funding: FundingModel
    swap: SwapModel

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not ID_PATTERN.fullmatch(self.id):
            raise CostConfigError(
                f"invalid cost profile id {self.id!r} (lower-case letters, digits and '_')"
            )
        if not isinstance(self.description, str):
            raise CostConfigError(f"cost profile {self.id!r}: description must be a string")
        for component, allowed in _COMPONENT_TYPES.items():
            value = getattr(self, component)
            if not isinstance(value, allowed):
                raise CostConfigError(
                    f"cost profile {self.id!r}: {component} must be one of "
                    f"{', '.join(cls.__name__ for cls in allowed)}, got {type(value).__name__}"
                )

    @property
    def session_windows(self) -> frozenset[str]:
        """Session-window ids this profile refers to (for catalog cross-validation)."""
        return self.spread.window_ids if isinstance(self.spread, SessionSpread) else frozenset()

    @classmethod
    def zero(cls, profile_id: str = "zero_cost") -> Self:
        """A frictionless profile (every component ``none``)."""
        return cls(
            id=profile_id,
            description="Frictionless: no spread, commission, slippage, funding or swap",
            spread=NoSpread(),
            commission=NoCommission(),
            slippage=NoSlippage(),
            funding=NoFunding(),
            swap=NoSwap(),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        if not isinstance(data, Mapping):
            raise CostConfigError(f"a cost profile must be a mapping, got {type(data).__name__}")
        profile_id = data.get("id")
        if not isinstance(profile_id, str):
            raise CostConfigError(f"a cost profile needs a string 'id', got {profile_id!r}")
        where = f"cost profile {profile_id!r}"
        allowed = {"id", "description", *_COMPONENTS}
        unknown = sorted(str(key) for key in data if key not in allowed)
        if unknown:
            raise CostConfigError(f"{where}: unknown field(s) {', '.join(unknown)}")
        missing = [name for name in _COMPONENTS if name not in data]
        if missing:
            raise CostConfigError(
                f"{where}: missing {', '.join(missing)} (write {{model: none}} for no cost)"
            )
        description = data.get("description", "")
        if not isinstance(description, str):
            raise CostConfigError(f"{where}: description must be a string")
        try:
            return cls(
                id=profile_id,
                description=description,
                spread=_parse_component(data["spread"], _SPREAD_PARSERS, "spread"),
                commission=_parse_component(data["commission"], _COMMISSION_PARSERS, "commission"),
                slippage=_parse_component(data["slippage"], _SLIPPAGE_PARSERS, "slippage"),
                funding=_parse_component(data["funding"], _FUNDING_PARSERS, "funding"),
                swap=_parse_component(data["swap"], _SWAP_PARSERS, "swap"),
            )
        except CostConfigError as exc:
            raise CostConfigError(f"{where}: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "spread": self.spread.to_dict(),
            "commission": self.commission.to_dict(),
            "slippage": self.slippage.to_dict(),
            "funding": self.funding.to_dict(),
            "swap": self.swap.to_dict(),
        }


def parse_cost_profiles(document: Mapping[str, Any]) -> dict[str, CostProfile]:
    """Read the ``cost_profiles`` list of a catalog document (other keys are ignored)."""
    if not isinstance(document, Mapping):
        raise CostConfigError(
            "a cost catalog document must be a mapping with a 'cost_profiles' list, "
            f"got {type(document).__name__}"
        )
    raw = document.get("cost_profiles")
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise CostConfigError("cost_profiles: expected a list of profiles")
    profiles: dict[str, CostProfile] = {}
    for index, item in enumerate(raw):
        try:
            profile = CostProfile.from_dict(item)
        except CostConfigError as exc:
            raise CostConfigError(f"cost_profiles[{index}]: {exc}") from exc
        if profile.id in profiles:
            raise CostConfigError(
                f"cost_profiles[{index}]: duplicate cost profile id {profile.id!r}"
            )
        profiles[profile.id] = profile
    return profiles


def cost_profiles_document(profiles: Iterable[CostProfile]) -> dict[str, Any]:
    """The inverse of :func:`parse_cost_profiles` (canonical, JSON/YAML-serializable)."""
    return {"cost_profiles": [profile.to_dict() for profile in profiles]}


#: Contract types that are never financed overnight: futures carry the cost in
#: the price (and are rolled), perpetuals are financed by funding instead.
_UNFINANCED = frozenset({ContractType.FUTURE, ContractType.PERPETUAL})


def profile_listing_problems(profile: CostProfile, listing: Listing) -> list[str]:
    """Why ``profile`` cannot cost ``listing`` (empty when it can).

    A profile is only meaningful for the contract type it was written for:
    funding exists only on perpetuals and overnight swap never applies to
    futures or perpetuals. Charging either on the wrong listing would silently
    bias long/short results, so the catalog validates every listing's profile
    with this and :class:`CostCalculator` refuses the pair.
    """
    problems: list[str] = []
    contract = listing.contract_type
    if not isinstance(profile.funding, NoFunding) and contract is not ContractType.PERPETUAL:
        problems.append(
            f"cost profile {profile.id!r} charges funding, which only applies to PERPETUAL "
            f"listings; {listing.key} is a {contract} (use a swap model for overnight financing)"
        )
    if not isinstance(profile.swap, NoSwap) and contract in _UNFINANCED:
        problems.append(
            f"cost profile {profile.id!r} charges overnight swap, which never applies to a "
            f"{contract} listing such as {listing.key}"
        )
    return problems


# ── results ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class CostEvent:
    """A time-based cost: a signed cash flow to the account (negative = paid)."""

    ts: datetime
    kind: str  # "FUNDING" | "SWAP" (CostEventKind)
    amount: Decimal
    detail: str
    currency: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts", ensure_utc(self.ts))
        try:
            object.__setattr__(self, "kind", CostEventKind(self.kind))
        except ValueError:
            raise ValueError(
                f"cost event kind must be one of {', '.join(CostEventKind)}, got {self.kind!r}"
            ) from None
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise ValueError(f"cost event amount must be a finite Decimal, got {self.amount!r}")


@dataclass(frozen=True, slots=True)
class FillPrice:
    """A simulated market/stop fill and how it was reached (price units, all >= 0).

    ``price = reference ± (half_spread + slippage + rounding)`` — plus for buys,
    minus for sells — so analytics can attribute spread and slippage separately.
    """

    side: OrderSide
    price: Decimal
    reference: Decimal  # the mid (market) or stop level the fill started from
    half_spread: Decimal
    slippage: Decimal
    rounding: Decimal  # adverse rounding to the listing's tick

    @property
    def adverse(self) -> Decimal:
        """Total distance from the reference against the trader."""
        return self.half_spread + self.slippage + self.rounding


# ── the calculator ───────────────────────────────────────────────────────────
type WindowLookup = Callable[[datetime], frozenset[str]]
"""Returns the ids of the session windows an instant falls into."""


class CostCalculator:
    """Applies one :class:`CostProfile` to one :class:`Listing`.

    Pure and stateless apart from its inputs: the same arguments always give
    the same result, so every lab account sharing a venue profile is costed
    identically. ``window_lookup`` returns the session-window ids an instant
    falls into; it is required when the spread model is ``session``.
    """

    __slots__ = ("_listing", "_profile", "_window_lookup")

    def __init__(
        self,
        profile: CostProfile,
        listing: Listing,
        window_lookup: WindowLookup | None = None,
    ) -> None:
        if (
            isinstance(profile.spread, SessionSpread)
            and profile.spread.by_window
            and window_lookup is None
        ):
            raise CostConfigError(
                f"cost profile {profile.id!r} uses a session spread; a window_lookup is required"
            )
        problems = profile_listing_problems(profile, listing)
        if problems:
            raise CostConfigError("; ".join(problems))
        self._profile = profile
        self._listing = listing
        self._window_lookup = window_lookup

    @property
    def profile(self) -> CostProfile:
        return self._profile

    @property
    def listing(self) -> Listing:
        return self._listing

    @property
    def currency(self) -> str:
        return self._listing.quote_currency

    # ── spread & slippage (price units) ─────────────────────────────────────
    @_exact
    def spread(self, at: datetime, quote: Quote | None = None) -> Decimal:
        """The full bid/ask spread at ``at`` in price units."""
        at = ensure_utc(at)
        model = self._profile.spread
        match model:
            case NoSpread():
                return _ZERO
            case FixedSpread(points=points):
                return points
            case FixedTicksSpread(ticks=ticks):
                return ticks * self._listing.tick_size
            case SessionSpread():
                lookup = self._window_lookup
                return model.points_for(lookup(at) if lookup is not None else frozenset())
            case QuoteSpread(fallback_points=fallback):
                if quote is None:
                    return fallback
                return self._checked_quote(quote, at).spread
            case _:  # pragma: no cover - exhaustive
                assert_never(model)

    @_exact
    def slippage(self, price: Decimal, at: datetime) -> Decimal:
        """Adverse slippage (>= 0, price units) for a market or stop fill near ``price``."""
        price = _require_positive(price, "price")
        ensure_utc(at)
        model = self._profile.slippage
        match model:
            case NoSlippage():
                return _ZERO
            case FixedTicksSlippage(ticks=ticks):
                return ticks * self._listing.tick_size
            case NotionalBpsSlippage(bps=bps):
                return price * bps / _BPS
            case _:  # pragma: no cover - exhaustive
                assert_never(model)

    # ── fills ───────────────────────────────────────────────────────────────
    @_exact
    def market_fill(
        self, side: OrderSide, mid: Decimal, at: datetime, quote: Quote | None = None
    ) -> FillPrice:
        """A market order: cross half the spread, pay slippage, round adversely.

        With a quote and the ``quotes`` spread model, the fill is the quote's
        ask (buy) or bid (sell) plus slippage, and ``mid`` is not used.
        """
        side = OrderSide(side)
        _require_positive(mid, "mid")
        at = ensure_utc(at)
        reference = mid
        if quote is not None and isinstance(self._profile.spread, QuoteSpread):
            reference = self._checked_quote(quote, at).mid
        half = self.spread(at, quote) / 2
        return self._adverse_fill(side, reference, half, self.slippage(reference, at))

    def market_fill_price(
        self, side: OrderSide, mid: Decimal, at: datetime, quote: Quote | None = None
    ) -> Decimal:
        """BUY = mid + spread/2 + slippage, SELL = mid − spread/2 − slippage, tick-rounded
        adversely. See :meth:`market_fill` for the breakdown."""
        return self.market_fill(side, mid, at, quote).price

    @_exact
    def stop_fill(
        self, side: OrderSide, stop_price: Decimal, at: datetime, quote: Quote | None = None
    ) -> FillPrice:
        """A triggered stop, treated as a mid-price level: a SELL stop fills
        below it (stop − spread/2 − slippage), a BUY stop above, rounded adversely.

        When a bar gaps through the stop the simulator passes the (worse) open
        as ``stop_price``.
        """
        side = OrderSide(side)
        _require_positive(stop_price, "stop_price")
        at = ensure_utc(at)
        half = self.spread(at, quote) / 2
        return self._adverse_fill(side, stop_price, half, self.slippage(stop_price, at))

    def stop_fill_price(
        self, side: OrderSide, stop_price: Decimal, at: datetime, quote: Quote | None = None
    ) -> Decimal:
        return self.stop_fill(side, stop_price, at, quote).price

    def limit_fill_price(self, side: OrderSide, limit_price: Decimal) -> Decimal:
        """A limit order fills exactly at its price: no spread crossing, no slippage,
        never better than the limit. (The order layer places limits on the tick grid.)"""
        OrderSide(side)
        return _require_positive(limit_price, "limit_price")

    # ── triggers (bars are mid prices) ──────────────────────────────────────
    @_exact
    def limit_triggered(
        self,
        side: OrderSide,
        limit_price: Decimal,
        bar_high_mid: Decimal,
        bar_low_mid: Decimal,
        at: datetime,
    ) -> bool:
        """Whether a resting limit fills within a mid-price bar.

        A SELL limit (a long's take-profit) needs the *bid* to reach it
        (high − spread/2 >= limit); a BUY limit (a short's take-profit) needs the
        *ask* (low + spread/2 <= limit). A target the mid merely touches does
        not fill.
        """
        side = OrderSide(side)
        _require_positive(limit_price, "limit_price")
        self._check_bar(bar_high_mid, bar_low_mid)
        half = self.spread(at) / 2
        if side is OrderSide.SELL:
            return bar_high_mid - half >= limit_price
        return bar_low_mid + half <= limit_price

    @_exact
    def stop_triggered(
        self,
        side: OrderSide,
        stop_price: Decimal,
        bar_high_mid: Decimal,
        bar_low_mid: Decimal,
        at: datetime,
    ) -> bool:
        """Whether a stop triggers within a mid-price bar.

        A SELL stop (a long's stop-loss) triggers when the *bid* reaches it
        (low − spread/2 <= stop); a BUY stop (a short's stop-loss) when the
        *ask* does (high + spread/2 >= stop) — i.e. earlier than the mid would.
        """
        side = OrderSide(side)
        _require_positive(stop_price, "stop_price")
        self._check_bar(bar_high_mid, bar_low_mid)
        half = self.spread(at) / 2
        if side is OrderSide.SELL:
            return bar_low_mid - half <= stop_price
        return bar_high_mid + half >= stop_price

    # ── commission (quote currency, >= 0) ───────────────────────────────────
    @_exact
    def commission(
        self, qty: Decimal, price: Decimal, liquidity: Liquidity = Liquidity.TAKER
    ) -> Decimal:
        """The fee for one fill (one side), rounded up to :data:`MONEY_QUANTUM`."""
        _require_positive(qty, "qty")
        _require_positive(price, "price")
        liquidity = Liquidity(liquidity)
        model = self._profile.commission
        match model:
            case NoCommission():
                return _fee(_ZERO)
            case PerQuantityCommission(per_side=per_side, minimum=minimum):
                return _fee(max(per_side * qty, minimum))
            case NotionalCommission(minimum=minimum):
                notional = self._listing.notional(qty, price)
                return _fee(max(notional * model.rate(liquidity), minimum))
            case _:  # pragma: no cover - exhaustive
                assert_never(model)

    # ── time-based costs (signed cash flows) ────────────────────────────────
    @_exact
    def funding_events(
        self,
        direction: Direction,
        qty: Decimal,
        mark_price: PriceSource,
        start: datetime,
        end: datetime,
    ) -> list[CostEvent]:
        """Funding for a position held over (start, end]: one event per funding
        instant t with start < t <= end. amount = −sign × rate × notional at the
        mark price at t (sign +1 long, −1 short): positive rates are paid by longs
        and received by shorts."""
        direction = Direction(direction)
        _require_positive(qty, "qty")
        start, end = _interval(start, end)
        model = self._profile.funding
        if isinstance(model, NoFunding):
            return []
        sign = 1 if direction is Direction.LONG else -1
        events: list[CostEvent] = []
        for instant in _funding_instants(model.anchor_hours, start, end):
            mark = _price_at(mark_price, instant, "mark_price")
            notional = self._listing.notional(qty, mark)
            amount = _cash_flow(-sign * model.rate_per_interval * notional)
            detail = (
                f"{direction} {qty} @ mark {mark}: rate {model.rate_per_interval} × "
                f"notional {notional}"
            )
            events.append(CostEvent(instant, CostEventKind.FUNDING, amount, detail, self.currency))
        return events

    @_exact
    def swap_events(
        self,
        direction: Direction,
        qty: Decimal,
        price: PriceSource,
        start: datetime,
        end: datetime,
    ) -> list[CostEvent]:
        """Swap for a position held over (start, end]: one event per weekday
        rollover t with start < t <= end; the triple-day rollover counts 3 nights."""
        direction = Direction(direction)
        _require_positive(qty, "qty")
        start, end = _interval(start, end)
        model = self._profile.swap
        if isinstance(model, NoSwap):
            return []
        events: list[CostEvent] = []
        rollovers = _rollover_instants(
            model.rollover_time,
            _zone(model.timezone, "swap timezone"),
            model.triple_day,
            start,
            end,
        )
        for instant, nights in rollovers:
            match model:
                case PointsSwap():
                    points = model.points(direction)
                    point_value = self._listing.point_value
                    amount = points * point_value * qty * nights
                    detail = f"{direction} {qty}: {nights} night(s) × {points} pts × {point_value}"
                case AnnualRateSwap():
                    rate = model.rate(direction)
                    mark = _price_at(price, instant, "price")
                    notional = self._listing.notional(qty, mark)
                    amount = -rate * notional * nights / model.day_count
                    detail = (
                        f"{direction} {qty} @ {mark}: {nights} night(s) × {rate}/{model.day_count}"
                        f" × notional {notional}"
                    )
                case _:  # pragma: no cover - exhaustive
                    assert_never(model)
            events.append(
                CostEvent(instant, CostEventKind.SWAP, _cash_flow(amount), detail, self.currency)
            )
        return events

    # ── internals ───────────────────────────────────────────────────────────
    def _adverse_fill(
        self, side: OrderSide, reference: Decimal, half_spread: Decimal, slippage: Decimal
    ) -> FillPrice:
        is_buy = side is OrderSide.BUY
        adverse = half_spread + slippage
        raw = reference + adverse if is_buy else reference - adverse
        price = self._listing.round_price(raw, is_buy=is_buy) if raw > 0 else raw
        if price <= 0:
            raise ValueError(
                f"{self._listing.key}: {side} fill from {reference} with spread/2 {half_spread} "
                f"and slippage {slippage} would be non-positive ({price})"
            )
        return FillPrice(
            side=side,
            price=price,
            reference=reference,
            half_spread=half_spread,
            slippage=slippage,
            rounding=price - raw if is_buy else raw - price,
        )

    def _checked_quote(self, quote: Quote, at: datetime) -> Quote:
        if quote.instrument != self._listing.instrument:
            raise ValueError(
                f"quote for {quote.instrument} cannot price {self._listing.key} "
                f"({self._listing.instrument})"
            )
        if quote.ts > at:
            raise ValueError(
                f"look-ahead: quote for {quote.instrument} at {quote.ts.isoformat()} is after "
                f"the fill instant {at.isoformat()}"
            )
        return quote

    @staticmethod
    def _check_bar(high: Decimal, low: Decimal) -> None:
        _require_positive(high, "bar_high_mid")
        _require_positive(low, "bar_low_mid")
        if high < low:
            raise ValueError(f"bar high {high} is below bar low {low}")


def _interval(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start, end = ensure_utc(start), ensure_utc(end)
    if end < start:
        raise ValueError(f"end {end.isoformat()} is before start {start.isoformat()}")
    return start, end


def _funding_instants(hours: tuple[int, ...], start: datetime, end: datetime) -> Iterator[datetime]:
    """Every ``hours`` UTC instant t of every day with start < t <= end, in order."""
    day = start.date()
    while day <= end.date():
        for hour in hours:
            instant = datetime.combine(day, time(hour), tzinfo=UTC)
            if start < instant <= end:
                yield instant
        day += timedelta(days=1)


def _rollover_instants(
    rollover_time: time, zone: ZoneInfo, triple_day: int, start: datetime, end: datetime
) -> Iterator[tuple[datetime, int]]:
    """Weekday rollovers t (UTC) with start < t <= end, and the nights each one counts.

    The rollover is a *local* time in ``zone``, so its UTC instant follows DST.
    A local time in a spring-forward gap resolves (``fold=0``) to the instant
    the gap's length later on the wall clock; an ambiguous one to its first
    occurrence — the same rule as the trading calendars.
    """
    day = start.astimezone(zone).date() - timedelta(days=1)
    last = end.astimezone(zone).date() + timedelta(days=1)
    while day <= last:
        weekday = day.weekday()
        if weekday < 5:  # Saturday and Sunday rollovers are skipped
            local = datetime.combine(day, rollover_time.replace(fold=0), tzinfo=zone)
            instant = local.astimezone(UTC)
            if start < instant <= end:
                yield instant, 3 if weekday == triple_day else 1
        day += timedelta(days=1)

"""``StrategyContext`` — the only window a strategy has on the world.

Everything here is read-only: the instrument, closed bar series for the
primary and context timeframes, the theoretical position, session/time-zone
helpers, a seeded random generator and a logger. The signal builders fill
in the strategy id, version, symbol, timeframe and timestamps and round
prices to the instrument's tick, so strategy code only expresses intent.
"""

import hashlib
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

import numpy as np
import structlog
from pydantic import JsonValue

from kterminal.core.enums import OrderType, SignalAction, SignalSource
from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import Timeframe
from kterminal.strategy_engine.book import TheoreticalBook
from kterminal.strategy_engine.model import PositionView
from kterminal.strategy_engine.series import BarSeries

Price = Decimal | float | int | str


class SessionLookup(Protocol):
    """What the context needs from the session book (``kterminal.domain.sessions``)."""

    def window(self, window_id: str) -> Any: ...

    def trading_day_rule(self, rule_id: str) -> Any: ...

    def classify(self, ts: datetime) -> str: ...


class NoSessions:
    """Placeholder when no session book is configured: every lookup fails clearly."""

    def window(self, window_id: str) -> Any:
        raise KeyError(f"no session book configured (requested window {window_id!r})")

    def trading_day_rule(self, rule_id: str) -> Any:
        raise KeyError(f"no session book configured (requested trading-day rule {rule_id!r})")

    def classify(self, ts: datetime) -> str:
        return "unknown"


def stable_seed(*parts: str) -> int:
    """Deterministic 64-bit seed (Python's hash() is salted per process)."""
    return int.from_bytes(hashlib.sha256("\x1f".join(parts).encode()).digest()[:8], "big")


class StrategyContext:
    def __init__(
        self,
        *,
        instance_id: str,
        definition_id: str,
        strategy_version: str,
        instrument: Instrument,
        timeframe: Timeframe,
        series: Mapping[Timeframe, BarSeries],
        book: TheoreticalBook,
        sessions: SessionLookup | None = None,
        source: SignalSource = SignalSource.INTERNAL,
    ) -> None:
        if timeframe not in series:
            raise ValueError(f"primary timeframe {timeframe} has no series")
        self.strategy_id = instance_id
        self.definition_id = definition_id
        self.strategy_version = strategy_version
        self.instrument = instrument
        self.timeframe = timeframe
        self._series = dict(series)
        self._book = book
        self._sessions: SessionLookup = sessions or NoSessions()
        self._source = source
        self._bar: Bar | None = None
        self.rng = np.random.default_rng(stable_seed(instance_id, instrument.symbol))
        self.log = structlog.stdlib.get_logger("kterminal.strategy").bind(
            strategy_id=instance_id, instrument=instrument.symbol, timeframe=timeframe.code
        )

    # ── data ────────────────────────────────────────────────────────────────
    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    @property
    def bars(self) -> BarSeries:
        """Closed bars of the primary timeframe; ``bars.close[-1]`` is the bar being evaluated."""
        return self._series[self.timeframe]

    def series(self, timeframe: Timeframe | str) -> BarSeries:
        """Closed bars of a declared context timeframe (higher TFs: only bars closed by now)."""
        tf = Timeframe.parse(timeframe)
        try:
            return self._series[tf]
        except KeyError:
            declared = ", ".join(sorted(t.code for t in self._series))
            raise KeyError(f"timeframe {tf} not declared for this instance ({declared})") from None

    @property
    def timeframes(self) -> tuple[Timeframe, ...]:
        return tuple(sorted(self._series))

    @property
    def bar(self) -> Bar:
        if self._bar is None:
            raise RuntimeError("no bar is being evaluated yet")
        return self._bar

    @property
    def now(self) -> datetime:
        """Strategy time: the close time of the bar being evaluated."""
        return self.bar.close_time

    @property
    def position(self) -> PositionView | None:
        return self._book.position

    # ── sessions & time zones ───────────────────────────────────────────────
    def window(self, window_id: str) -> Any:
        """A configured session window (e.g. ``ny_orb_15``) with ``contains`` / ``window_on``."""
        return self._sessions.window(window_id)

    def in_window(self, window_id: str, ts: datetime | None = None) -> bool:
        return bool(self._sessions.window(window_id).contains(ts or self.now))

    def trading_day(self, ts: datetime | None = None) -> date:
        """Trading day per the instrument's rollover rule (e.g. 17:00 New York)."""
        rule = self._sessions.trading_day_rule(self.instrument.trading_day)
        result: date = rule.trading_day(ts or self.now)
        return result

    def session(self, ts: datetime | None = None) -> str:
        """Session label (e.g. ``asia_session`` / ``london_session`` / ``ny_session``)."""
        return self._sessions.classify(ts or self.now)

    # ── signal builders ─────────────────────────────────────────────────────
    def long(
        self,
        *,
        stop_loss: Price,
        take_profit: Price | None = None,
        entry: Price | None = None,
        order_type: OrderType = OrderType.MARKET,
        risk: Price | None = None,
        confidence: float | None = None,
        expires_after_bars: int | None = None,
        reason: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Signal:
        return self._entry(
            SignalAction.LONG,
            stop_loss,
            take_profit,
            entry,
            order_type,
            risk,
            confidence,
            expires_after_bars,
            reason,
            metadata,
        )

    def short(
        self,
        *,
        stop_loss: Price,
        take_profit: Price | None = None,
        entry: Price | None = None,
        order_type: OrderType = OrderType.MARKET,
        risk: Price | None = None,
        confidence: float | None = None,
        expires_after_bars: int | None = None,
        reason: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Signal:
        return self._entry(
            SignalAction.SHORT,
            stop_loss,
            take_profit,
            entry,
            order_type,
            risk,
            confidence,
            expires_after_bars,
            reason,
            metadata,
        )

    def exit_long(
        self, *, reason: str | None = None, metadata: Mapping[str, JsonValue] | None = None
    ) -> Signal:
        return self._make(
            SignalAction.EXIT_LONG,
            entry=self._price(self.bar.close),
            reason=reason,
            metadata=metadata,
        )

    def exit_short(
        self, *, reason: str | None = None, metadata: Mapping[str, JsonValue] | None = None
    ) -> Signal:
        return self._make(
            SignalAction.EXIT_SHORT,
            entry=self._price(self.bar.close),
            reason=reason,
            metadata=metadata,
        )

    def move_sl(
        self,
        stop_loss: Price,
        *,
        take_profit: Price | None = None,
        reason: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Signal:
        return self._make(
            SignalAction.MOVE_SL,
            stop_loss=self._price(stop_loss),
            take_profit=self._price(take_profit),
            reason=reason,
            metadata=metadata,
        )

    def no_trade(
        self,
        reason: str,
        *,
        persist: bool = False,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Signal:
        return self._make(SignalAction.NO_TRADE, reason=reason, persist=persist, metadata=metadata)

    # ── internals ───────────────────────────────────────────────────────────
    def _entry(
        self,
        action: SignalAction,
        stop_loss: Price,
        take_profit: Price | None,
        entry: Price | None,
        order_type: OrderType,
        risk: Price | None,
        confidence: float | None,
        expires_after_bars: int | None,
        reason: str | None,
        metadata: Mapping[str, JsonValue] | None,
    ) -> Signal:
        if entry is None and order_type is not OrderType.MARKET:
            raise ValueError(f"{order_type} entries need an explicit entry price")
        return self._make(
            action,
            entry=self._price(entry if entry is not None else self.bar.close),
            stop_loss=self._price(stop_loss),
            take_profit=self._price(take_profit),
            order_type=order_type,
            risk=_to_decimal(risk) if risk is not None else None,
            confidence=confidence,
            expires_after_bars=expires_after_bars,
            reason=reason,
            metadata=metadata,
        )

    def _price(self, value: Price | None) -> Decimal | None:
        if value is None:
            return None
        return self.instrument.round_price(_to_decimal(value))

    def _make(self, action: SignalAction, **fields: Any) -> Signal:
        bar = self.bar
        metadata = fields.pop("metadata", None)
        return Signal(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            symbol=self.instrument.symbol,
            timeframe=self.timeframe.code,
            timestamp=bar.close_time,
            bar_time=bar.open_time,
            signal=action,
            source=self._source,
            metadata=dict(metadata or {}),
            **{k: v for k, v in fields.items() if v is not None},
        )

    def _set_bar(self, bar: Bar) -> None:
        self._bar = bar


def _to_decimal(value: Price) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError(f"price must be finite, got {value}")
        return Decimal(repr(value))
    return Decimal(value)

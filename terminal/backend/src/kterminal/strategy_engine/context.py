"""``StrategyContext`` — the only window a strategy has on the world.

Everything here is read-only: the instrument, closed bar series for the
primary and context timeframes (also as TradingView's ``request.security``
sees them), the primary bar index, previous/current trading day, week and
month levels, the theoretical position and resting entry, whether the runner is
replaying warm-up bars, session/time-zone helpers (catalog windows and Pine
session strings), a seeded random generator and a logger.
The signal builders fill in the strategy id, version, symbol, timeframe and
timestamps and round prices to the instrument's tick, so strategy code only
expresses intent.
"""

import hashlib
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, overload

import numpy as np
import structlog
from pydantic import JsonValue

from kterminal.core.enums import OrderType, SignalAction, SignalSource
from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import Timeframe
from kterminal.strategy_engine.book import TheoreticalBook
from kterminal.strategy_engine.model import CloseReason, PendingEntryView, PositionView
from kterminal.strategy_engine.periods import PeriodLevels
from kterminal.strategy_engine.series import BarSeries, SeriesView
from kterminal.strategy_engine.sessions import SessionSpec, parse_session

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
        windows: Iterable[str] | None = None,
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
        # Session windows the strategy may use: the ones its version is built from
        # (declared in meta.sessions, plus the session classification). None = any.
        self._windows = frozenset(windows) if windows is not None else None
        self._source = source
        self._bar: Bar | None = None
        self._warming_up = False  # set by the runner while it replays warm-up bars
        self._primary_bars = 0  # every primary bar seen, warm-up included (bar_index)
        self._last_open: datetime | None = None  # open time of the latest primary bar
        self._previous_open: datetime | None = None  # … and of the one before it
        self._periods: PeriodLevels | None = None
        self._periods_error = ""
        try:
            self._periods = PeriodLevels(self._sessions.trading_day_rule(instrument.trading_day))
        except KeyError as exc:
            self._periods_error = str(exc)
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

    @overload
    def series(
        self, timeframe: Timeframe | str, *, tradingview_lag: Literal[False] = False
    ) -> BarSeries: ...

    @overload
    def series(
        self, timeframe: Timeframe | str, *, tradingview_lag: Literal[True]
    ) -> SeriesView: ...

    def series(
        self, timeframe: Timeframe | str, *, tradingview_lag: bool = False
    ) -> BarSeries | SeriesView:
        """Closed bars of a declared timeframe.

        By default a higher-timeframe bar is visible from the primary bar that closes
        at the same instant (it has closed by ``ctx.now``). With ``tradingview_lag=True``
        only bars that closed at or before the evaluated bar *opened* are visible —
        what Pine's ``request.security(sym, tf, expr[1], lookahead=barmerge.lookahead_on)``
        returns, one primary bar later on the last bar of each period. Only for the
        primary timeframe or higher ones (on the primary series it hides the bar being
        evaluated, like ``expr[1]``).
        """
        tf = Timeframe.parse(timeframe)
        try:
            series = self._series[tf]
        except KeyError:
            declared = ", ".join(sorted(t.code for t in self._series))
            raise KeyError(f"timeframe {tf} not declared for this instance ({declared})") from None
        if not tradingview_lag:
            return series
        if tf < self.timeframe:
            raise ValueError(
                f"tradingview_lag applies to the primary timeframe {self.timeframe} or higher "
                f"ones, not {tf}"
            )
        return series.closed_by(self.bar.open_time)

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
    def bar_index(self) -> int:
        """Index of the evaluated bar among every primary bar this instance has seen,
        warm-up included — 0 on the first, like Pine's ``bar_index``. Not capped by
        the length of ``bars``."""
        if self._primary_bars == 0:
            raise RuntimeError("no bar is being evaluated yet")
        return self._primary_bars - 1

    @property
    def periods(self) -> PeriodLevels:
        """Previous and current trading day / week / month (OHLC) of the instrument,
        built from the primary bars on its trading-day rule: ``ctx.periods.previous("D")``
        is the previous day (PDH = ``.high``), ``ctx.periods.current("W")`` this week."""
        if self._periods is None:
            raise KeyError(
                f"no trading-day rule for {self.instrument.symbol} "
                f"({self.instrument.trading_day}): {self._periods_error}"
            )
        return self._periods

    @property
    def position(self) -> PositionView | None:
        """This instance's theoretical position on the symbol, or None."""
        return self._book.position

    @property
    def pending_entry(self) -> PendingEntryView | None:
        """The theoretical book's resting entry order on the symbol (a LIMIT/STOP entry
        that has not filled, expired or been cancelled yet), or None."""
        return self._book.pending_entry

    @property
    def warming_up(self) -> bool:
        """True while the runner replays warm-up bars: signals returned now are discarded
        and the theoretical book stays flat."""
        return self._warming_up

    # ── sessions & time zones ───────────────────────────────────────────────
    # Without an explicit ``ts`` these helpers look at the evaluated bar's *open* time
    # — the bar belongs to the window/session/trading day it starts in, exactly like
    # Pine's ``time``-based session filters. (``now``, the close, is the first instant
    # *after* the bar.)
    def window(self, window_id: str) -> Any:
        """A configured session window (e.g. ``ny_orb_15``) with ``contains`` / ``window_on``.

        Only windows in ``meta.sessions`` (or the session classification) are available,
        so that every window a strategy depends on is part of its version.
        """
        if self._windows is not None and window_id not in self._windows:
            raise KeyError(
                f"session window {window_id!r} is not declared: add it to meta.sessions "
                f"(declared: {', '.join(sorted(self._windows)) or 'none'})"
            )
        return self._sessions.window(window_id)

    def in_window(self, window_id: str, ts: datetime | None = None) -> bool:
        """Whether the evaluated bar (or ``ts``) is inside the window."""
        return bool(self.window(window_id).contains(ts or self.bar.open_time))

    def trading_day(self, ts: datetime | None = None) -> date:
        """Trading day of the evaluated bar (or ``ts``) per the instrument's rollover rule
        (e.g. 17:00 New York)."""
        rule = self._sessions.trading_day_rule(self.instrument.trading_day)
        result: date = rule.trading_day(ts or self.bar.open_time)
        return result

    def session(self, ts: datetime | None = None) -> str:
        """Session label of the evaluated bar (or ``ts``), e.g. ``asia_session`` /
        ``london_session`` / ``ny_session``."""
        return self._sessions.classify(ts or self.bar.open_time)

    # Pine session strings (kept as Params, so they are part of the version):
    # ``"2000-0200:1234567"`` in an IANA zone — see kterminal.strategy_engine.sessions.
    def in_session(
        self, session: str | SessionSpec, timezone: str, ts: datetime | None = None
    ) -> bool:
        """Whether the evaluated bar (or ``ts``) opens inside a Pine session string, like
        ``not na(time(timeframe.period, session, timezone))``."""
        return _spec(session, timezone).contains(ts or self.bar.open_time)

    def session_started(self, session: str | SessionSpec, timezone: str) -> bool:
        """Whether the evaluated bar starts the window: it is inside and the previous
        primary bar was not (or there is none) — Pine's ``inSess and not inSess[1]``."""
        return _spec(session, timezone).started(self.bar.open_time, self._previous_open)

    def session_ends(self, session: str | SessionSpec, timezone: str) -> bool:
        """Whether the evaluated bar is the last one of the window (inside, and the window
        ends by its close): an exit decided now fills at the window's end."""
        bar = self.bar
        return _spec(session, timezone).ends_by(bar.open_time, bar.close_time)

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
        self,
        *,
        reason: str | None = None,
        session_close: bool = False,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Signal:
        """Close the long position at the next open (or cancel a resting long entry).
        ``session_close=True`` records the exit as ``SESSION_CLOSE`` (a time exit)."""
        return self._make(
            SignalAction.EXIT_LONG,
            entry=self._price(self.bar.close),
            reason=_exit_reason(reason, session_close),
            metadata=metadata,
        )

    def exit_short(
        self,
        *,
        reason: str | None = None,
        session_close: bool = False,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Signal:
        """Close the short position at the next open (or cancel a resting short entry).
        ``session_close=True`` records the exit as ``SESSION_CLOSE`` (a time exit)."""
        return self._make(
            SignalAction.EXIT_SHORT,
            entry=self._price(self.bar.close),
            reason=_exit_reason(reason, session_close),
            metadata=metadata,
        )

    def flatten(
        self,
        *,
        reason: str = CloseReason.SESSION_CLOSE.value,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Signal:
        """Close whatever this instance holds on the symbol — in either direction, in the
        theoretical book and in the account alike, even when the book is already flat —
        at the next base bar's open, and cancel any resting entry. Changes nothing when
        there is nothing to close (no decision row). The trade's exit reason is
        ``SESSION_CLOSE`` for the default ``reason``, ``SIGNAL_EXIT`` for any other.
        Always permitted, also under a kill switch."""
        return self._make(
            SignalAction.FLATTEN,
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

    def _advance(self, bar: Bar) -> None:
        """A primary bar closed (warm-up included): count it and update period levels."""
        self._primary_bars += 1
        self._previous_open, self._last_open = self._last_open, bar.open_time
        if self._periods is not None:
            self._periods.update(bar)


def _spec(session: str | SessionSpec, timezone: str) -> SessionSpec:
    if isinstance(session, SessionSpec):
        if session.timezone != timezone:
            raise ValueError(f"session {session.text!r} is in {session.timezone}, not {timezone}")
        return session
    return parse_session(session, timezone)


def _exit_reason(reason: str | None, session_close: bool) -> str | None:
    if not session_close:
        return reason
    if reason not in (None, CloseReason.SESSION_CLOSE):
        raise ValueError("a session-close exit records the reason SESSION_CLOSE; drop reason")
    return CloseReason.SESSION_CLOSE.value


def _to_decimal(value: Price) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError(f"price must be finite, got {value}")
        return Decimal(repr(value))
    return Decimal(value)

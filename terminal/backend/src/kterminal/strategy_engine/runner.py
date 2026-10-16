"""Drives one strategy instance on one instrument.

For every batch of bars that closed at the same instant the runner:

1. appends the bars of its instrument and timeframes to its own series
   (context timeframes first, so higher timeframes are visible exactly when
   they have closed and never before);
2. with an execution model (the lab), advances the theoretical book on the
   batch's **base** bar of its instrument exactly as the instance's account
   does (fills at its open on bid/ask, SL/TP); the book's events wait for the
   primary bar that contains it;
3. if a primary-timeframe bar closed: counts it (``ctx.bar_index``) and updates
   the trading day / week / month levels (``ctx.periods``) — during warm-up too —
   ends the bar in the book (expiry; without an execution model the book
   resolves the whole primary bar at mid prices here), lets the strategy react to
   position events, then calls ``on_bar``;
4. checks every returned object is a ``Signal`` carrying *this* instance's
   identity, validates it against the standard, and applies valid ones to the
   book — keeping the book's answer: a signal the book ignored (``POSITION_EXISTS``,
   ``NO_MATCHING_POSITION`` …) is reported with that reason in
   :attr:`RunnerOutput.book_reasons`.

Strategy exceptions — including ``SystemExit`` and other ``BaseException``
subclasses, but not an operator's ``KeyboardInterrupt`` — are caught: the
runner records a :class:`Fault` and stops emitting signals (fail closed).
Strategy code runs in its own copy of the decimal context, returned signals are
re-validated from scratch (``model_copy`` skips validation) and must carry the
evaluated bar's identity, and a strategy may return at most
:data:`MAX_OUTPUTS_PER_BAR` objects per bar. Nothing a strategy does can raise
past the runner, so other instances are unaffected.
"""

import json
import time
import traceback
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from decimal import localcontext
from functools import partial
from typing import Any

from pydantic import ValidationError

from kterminal.core.enums import SignalSource
from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.signals import (
    MAX_METADATA_BYTES,
    InvalidSignalError,
    Signal,
    validate_signal,
)
from kterminal.strategy_engine.base import Strategy
from kterminal.strategy_engine.book import TheoreticalBook
from kterminal.strategy_engine.context import SessionLookup, StrategyContext
from kterminal.strategy_engine.fills import BookExecution
from kterminal.strategy_engine.instances import ResolvedInstance
from kterminal.strategy_engine.model import (
    BookState,
    Fault,
    PositionEvent,
    RejectedSignal,
    RunnerOutput,
)
from kterminal.strategy_engine.series import DEFAULT_MAX_BARS, BarSeries

DEFAULT_TIME_BUDGET_MS = 250.0
MAX_OUTPUTS_PER_BAR = 64  # more than this from one bar is a runaway strategy: fault it
MAX_REJECTED_PAYLOAD_BYTES = 2 * MAX_METADATA_BYTES


def _contain(exc: BaseException) -> bool:
    """Whether a strategy's exception is contained (everything but an operator interrupt)."""
    return not isinstance(exc, KeyboardInterrupt)


def _isolated[T](call: Callable[[], T]) -> T:
    """Run strategy code in a private copy of the decimal context, so a strategy that
    changes precision, rounding or traps cannot change anyone else's arithmetic."""
    with localcontext():
        return call()


class StrategyRunner:
    def __init__(
        self,
        resolved: ResolvedInstance,
        instrument: Instrument,
        *,
        sessions: SessionLookup | None = None,
        max_bars: int = DEFAULT_MAX_BARS,
        time_budget_ms: float = DEFAULT_TIME_BUDGET_MS,
        execution: BookExecution | None = None,
    ) -> None:
        """``execution`` makes the theoretical book resolve orders like the instance's
        account: on its base bars, with its prices (``kterminal.strategy_engine.fills``)."""
        self.resolved = resolved
        self.instrument = instrument
        self.time_budget_ms = time_budget_ms
        self.execution = execution
        meta = resolved.definition.meta
        self.series = {
            tf: BarSeries(instrument.symbol, tf, max(max_bars, meta.warmup_bars + 1))
            for tf in resolved.timeframes
        }
        rules = resolved.position_rules  # the instance's accounts apply the same rules
        self.book = TheoreticalBook(
            instrument.symbol,
            on_opposite_signal=rules.on_opposite_signal,
            skip_entry_beyond_levels=rules.skip_entry_beyond_levels,
            execution=execution,
        )
        self._book_events: list[PositionEvent] = []  # base-bar events of the current bar
        self.source = (
            SignalSource.INTERNAL
            if resolved.definition.strategy_cls is not None
            else SignalSource.TRADINGVIEW
        )
        self.ctx = StrategyContext(
            instance_id=resolved.id,
            definition_id=resolved.definition.id,
            strategy_version=resolved.version,
            instrument=instrument,
            timeframe=resolved.timeframe,
            series=self.series,
            book=self.book,
            sessions=sessions,
            source=self.source,
            windows=(
                None
                if sessions is None
                else (
                    *resolved.definition.meta.sessions,
                    *getattr(sessions, "classification", ()),
                )
            ),
        )
        self.fault: Fault | None = None
        self.warming_up = False
        self.bars_evaluated = 0
        self.max_elapsed_ms = 0.0
        self.slow_bars = 0
        self._strategy: Strategy[Any] | None = None
        self._started = False

    @property
    def instance_id(self) -> str:
        return self.resolved.id

    @property
    def is_external(self) -> bool:
        return self.resolved.definition.strategy_cls is None

    # ── lifecycle ───────────────────────────────────────────────────────────
    def start(self) -> Fault | None:
        if self._started:
            return self.fault
        self._started = True
        cls = self.resolved.definition.strategy_cls
        if cls is None:
            return None
        try:
            # Each strategy object gets its own deep copy of the params: runners of one
            # instance (one per instrument) must not share anything mutable.
            params = self.resolved.params.model_copy(deep=True)
            strategy = _isolated(lambda: cls(params, self.ctx))
            self._strategy = strategy
            _isolated(strategy.on_start)
        except BaseException as exc:
            if not _contain(exc):
                raise
            self._record_fault("on_start", exc, None)
        return self.fault

    def warmup(self, bars: Iterable[Bar]) -> None:
        """Replay history so indicators are primed. Signals are discarded and the
        theoretical book stays flat, so live trading starts from a clean slate."""
        self.warming_up = True
        self.ctx._warming_up = True
        try:
            batch: list[Bar] = []
            for bar in sorted(bars, key=lambda b: (b.close_time, b.timeframe)):
                if batch and bar.close_time != batch[0].close_time:
                    self.process(batch)
                    batch = []
                batch.append(bar)
            if batch:
                self.process(batch)
        finally:
            self.warming_up = False
            self.ctx._warming_up = False

    def stop(self) -> None:
        if self._strategy is not None and self.fault is None:
            try:
                _isolated(self._strategy.on_stop)
            except BaseException as exc:
                if not _contain(exc):
                    raise
                self._record_fault("on_stop", exc, None)

    # ── bars ────────────────────────────────────────────────────────────────
    def process(self, bars: Sequence[Bar]) -> RunnerOutput | None:
        """Feed bars that closed at one instant. Returns output when a primary bar closed —
        or, with an execution model, when a base bar advanced the book (``book`` only)."""
        symbol = self.instrument.symbol
        mine = [b for b in bars if b.instrument == symbol and b.timeframe in self.series]
        base = self._base_bar(bars)
        if not mine and base is None:
            return None
        primary: Bar | None = None
        for bar in sorted(mine, key=lambda b: b.timeframe, reverse=True):
            self.series[bar.timeframe]._append(bar)
            if bar.timeframe == self.resolved.timeframe:
                primary = bar
        if primary is not None:
            self.ctx._advance(primary)
        if self.fault is not None or not self._started:
            return None
        if base is not None and not self.warming_up:
            self._book_events.extend(self.book.on_base_bar(base))
        if primary is None:
            if base is None or self.warming_up:
                return None
            return RunnerOutput(
                self.instance_id, symbol, base.close_time, book=self._book_state(base.close_time)
            )
        if self.is_external:
            return RunnerOutput(
                self.instance_id,
                symbol,
                primary.close_time,
                events=tuple(self._advance_book(primary)),
                book=self._book_state(primary.close_time),
            )

        started = time.perf_counter()
        events: list[PositionEvent] = []
        raw: list[Any] = []
        stage = "on_bar"
        try:
            self.ctx._set_bar(primary)
            if not self.warming_up:
                events = self._advance_book(primary)
            strategy = self._strategy
            if strategy is None:  # pragma: no cover - start() always sets it for internal
                raise RuntimeError("strategy not started")
            stage = "on_position_event"
            for event in events:
                raw.extend(_as_list(_isolated(partial(strategy.on_position_event, event))))
            stage = "on_bar"
            raw.extend(_as_list(_isolated(lambda: strategy.on_bar(primary))))
            if len(raw) > MAX_OUTPUTS_PER_BAR:
                stage = "output"
                raise RuntimeError(
                    f"returned {len(raw)} objects for one bar (max {MAX_OUTPUTS_PER_BAR})"
                )
        except BaseException as exc:
            if not _contain(exc):
                raise
            fault = self._record_fault(stage, exc, primary.close_time)
            return RunnerOutput(
                self.instance_id, symbol, primary.close_time, events=tuple(events), fault=fault
            )
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.bars_evaluated += 1
            self.max_elapsed_ms = max(self.max_elapsed_ms, elapsed)
            if elapsed > self.time_budget_ms:
                self.slow_bars += 1
                self.ctx.log.warning(
                    "strategy.slow_bar", elapsed_ms=round(elapsed, 2), budget_ms=self.time_budget_ms
                )

        if self.warming_up:
            return None
        signals, reasons, rejected = self._accept(raw, primary.close_time, primary)
        return RunnerOutput(
            self.instance_id,
            symbol,
            primary.close_time,
            signals=tuple(signals),
            rejected=tuple(rejected),
            events=tuple(events),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            book_reasons=tuple(reasons),
            book=self._book_state(primary.close_time),
        )

    def submit_external(self, signal: Signal) -> RunnerOutput:
        """Apply a validated external (TradingView) signal to this instance's book."""
        signals, reasons, rejected = self._accept([signal], signal.timestamp)
        return RunnerOutput(
            self.instance_id,
            self.instrument.symbol,
            signal.timestamp,
            signals=tuple(signals),
            rejected=tuple(rejected),
            book_reasons=tuple(reasons),
            book=self._book_state(signal.timestamp),
        )

    # ── internals ───────────────────────────────────────────────────────────
    def _base_bar(self, bars: Sequence[Bar]) -> Bar | None:
        """This instrument's base bar in the batch, when the book resolves on base bars."""
        execution = self.execution
        if execution is None:
            return None
        symbol = self.instrument.symbol
        for bar in bars:
            if bar.instrument == symbol and bar.timeframe == execution.base_timeframe:
                return bar
        return None

    def _advance_book(self, bar: Bar) -> list[PositionEvent]:
        """A primary bar closed: the events the strategy is told about. With an execution
        model the base bars inside it already resolved the orders; without one the book
        resolves the primary bar itself (mid prices)."""
        if self.execution is None:
            return self.book.on_bar(bar)
        events, self._book_events = self._book_events, []
        return [*events, *self.book.end_bar(bar.close_time)]

    def _book_state(self, at: datetime) -> BookState | None:
        return self.book.state(at) if self.execution is not None else None

    def _accept(
        self, raw: list[Any], at: datetime, bar: Bar | None = None
    ) -> tuple[list[Signal], list[str | None], list[RejectedSignal]]:
        accepted: list[Signal] = []
        reasons: list[str | None] = []
        rejected: list[RejectedSignal] = []
        for item in raw:
            if not isinstance(item, Signal):
                rejected.append(self._reject(at, "NOT_A_SIGNAL", f"returned {type(item).__name__}"))
                continue
            try:
                # Re-validate from scratch: model_copy(update=...) skips type validation, so
                # only a freshly validated copy (never the strategy's object) is routed.
                signal = Signal.model_validate(item.model_dump(warnings=False))
            except (ValidationError, TypeError, ValueError, ArithmeticError) as exc:
                rejected.append(self._reject(at, "INVALID_SIGNAL", _first_line(exc), item))
                continue
            mismatch = self._identity_mismatch(signal, bar)
            if mismatch:
                rejected.append(self._reject(at, "IDENTITY_MISMATCH", mismatch, item))
                continue
            try:
                validate_signal(signal)
            except InvalidSignalError as exc:
                rejected.append(self._reject(at, exc.code, exc.message, item))
                continue
            except (TypeError, ValueError, ArithmeticError) as exc:
                rejected.append(self._reject(at, "INVALID_SIGNAL", _first_line(exc), item))
                continue
            reason = self.book.apply(signal)
            if reason is not None:
                self.ctx.log.debug(
                    "strategy.signal_ignored", action=signal.signal.value, reason=reason
                )
            accepted.append(signal)
            reasons.append(reason)
        return accepted, reasons, rejected

    def _identity_mismatch(self, signal: Signal, bar: Bar | None) -> str | None:
        expected: dict[str, Any] = {
            "strategy_id": self.instance_id,
            "strategy_version": self.resolved.version,
            "symbol": self.instrument.symbol,
            "timeframe": self.resolved.timeframe.code,
            "source": self.source,
        }
        if bar is not None:  # internal strategies decide at the close of the evaluated bar
            expected["timestamp"] = bar.close_time
            expected["bar_time"] = bar.open_time
        for name, value in expected.items():
            if getattr(signal, name) != value:
                return f"{name} is {getattr(signal, name)!r}, expected {value!r}"
        return None

    def _reject(
        self, at: datetime, code: str, message: str, signal: Signal | None = None
    ) -> RejectedSignal:
        self.ctx.log.warning("strategy.signal_rejected", code=code, detail=message[:500])
        return RejectedSignal(
            instance_id=self.instance_id,
            instrument=self.instrument.symbol,
            time=at,
            code=code,
            message=message[:2_000].replace("\x00", "\ufffd"),
            payload=_safe_payload(signal) if signal is not None else {},
        )

    def _record_fault(self, stage: str, exc: BaseException, at: datetime | None) -> Fault:
        self.fault = Fault(
            instance_id=self.instance_id,
            instrument=self.instrument.symbol,
            time=at,
            stage=stage,
            error_type=type(exc).__name__,
            message=str(exc)[:2_000],
            traceback="".join(traceback.format_exception(exc))[-8_000:],
        )
        self.ctx.log.error(
            "strategy.faulted", stage=stage, error=type(exc).__name__, detail=str(exc)[:500]
        )
        return self.fault


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0] if text else ''}"[:500]


def _safe_payload(signal: Signal) -> dict[str, Any]:
    """The rejected signal as storable JSON: never raises, no NaN/Infinity, no NUL
    characters (PostgreSQL text/jsonb cannot hold them), bounded size."""
    try:
        payload = signal.model_dump(mode="json", fallback=repr, warnings=False)
        text = json.dumps(payload, allow_nan=False)
        if "\\u0000" in text:
            payload = json.loads(text.replace("\\u0000", "\\ufffd"))
    except (TypeError, ValueError, ArithmeticError):
        return {"unserializable": repr(signal)[:MAX_REJECTED_PAYLOAD_BYTES].replace("\x00", "")}
    if len(text) > MAX_REJECTED_PAYLOAD_BYTES:
        payload["metadata"] = {"truncated_bytes": len(text)}
        payload = {k: v for k, v in payload.items() if k != "reason"} | {
            "reason": str(payload.get("reason") or "")[:500]
        }
    return dict(payload)


def _as_list(output: object) -> list[Any]:
    if output is None:
        return []
    if isinstance(output, Signal):
        return [output]
    if isinstance(output, (list, tuple)):
        return list(output)
    return [output]  # rejected later as NOT_A_SIGNAL

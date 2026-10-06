"""Drives one strategy instance on one instrument.

For every batch of bars that closed at the same instant the runner:

1. appends the bars of its instrument and timeframes to its own series
   (context timeframes first, so higher timeframes are visible exactly when
   they have closed and never before);
2. if a primary-timeframe bar closed: advances the theoretical book (fills at
   the bar's open, SL/TP), lets the strategy react to position events, then
   calls ``on_bar``;
3. checks every returned object is a ``Signal`` carrying *this* instance's
   identity, validates it against the standard, and applies valid ones to the
   book.

Strategy exceptions are caught: the runner records a :class:`Fault` and stops
emitting signals (fail closed). Nothing a strategy does can raise past the
runner, so other instances are unaffected.
"""

import time
import traceback
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from kterminal.core.enums import SignalSource
from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.signals import InvalidSignalError, Signal, validate_signal
from kterminal.strategy_engine.base import Strategy
from kterminal.strategy_engine.book import TheoreticalBook
from kterminal.strategy_engine.context import SessionLookup, StrategyContext
from kterminal.strategy_engine.instances import ResolvedInstance
from kterminal.strategy_engine.model import Fault, PositionEvent, RejectedSignal, RunnerOutput
from kterminal.strategy_engine.series import DEFAULT_MAX_BARS, BarSeries

DEFAULT_TIME_BUDGET_MS = 250.0


class StrategyRunner:
    def __init__(
        self,
        resolved: ResolvedInstance,
        instrument: Instrument,
        *,
        sessions: SessionLookup | None = None,
        max_bars: int = DEFAULT_MAX_BARS,
        time_budget_ms: float = DEFAULT_TIME_BUDGET_MS,
    ) -> None:
        self.resolved = resolved
        self.instrument = instrument
        self.time_budget_ms = time_budget_ms
        meta = resolved.definition.meta
        self.series = {
            tf: BarSeries(instrument.symbol, tf, max(max_bars, meta.warmup_bars + 1))
            for tf in resolved.timeframes
        }
        self.book = TheoreticalBook(instrument.symbol, on_opposite_signal=meta.on_opposite_signal)
        self.ctx = StrategyContext(
            instance_id=resolved.id,
            definition_id=resolved.definition.id,
            strategy_version=resolved.version,
            instrument=instrument,
            timeframe=resolved.timeframe,
            series=self.series,
            book=self.book,
            sessions=sessions,
            source=SignalSource.INTERNAL
            if resolved.definition.strategy_cls is not None
            else SignalSource.TRADINGVIEW,
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
            self._strategy = cls(self.resolved.params, self.ctx)
            self._strategy.on_start()
        except Exception as exc:
            self._record_fault("on_start", exc, None)
        return self.fault

    def warmup(self, bars: Iterable[Bar]) -> None:
        """Replay history so indicators are primed. Signals are discarded and the
        theoretical book stays flat, so live trading starts from a clean slate."""
        self.warming_up = True
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

    def stop(self) -> None:
        if self._strategy is not None and self.fault is None:
            try:
                self._strategy.on_stop()
            except Exception as exc:
                self._record_fault("on_stop", exc, None)

    # ── bars ────────────────────────────────────────────────────────────────
    def process(self, bars: Sequence[Bar]) -> RunnerOutput | None:
        """Feed bars that closed at one instant. Returns output when a primary bar closed."""
        symbol = self.instrument.symbol
        mine = [b for b in bars if b.instrument == symbol and b.timeframe in self.series]
        if not mine:
            return None
        primary: Bar | None = None
        for bar in sorted(mine, key=lambda b: b.timeframe, reverse=True):
            self.series[bar.timeframe]._append(bar)
            if bar.timeframe == self.resolved.timeframe:
                primary = bar
        if primary is None:
            return None
        if self.fault is not None or not self._started:
            return None
        if self.is_external:
            return RunnerOutput(
                self.instance_id,
                symbol,
                primary.close_time,
                events=tuple(self._advance_book(primary)),
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
                raw.extend(_as_list(strategy.on_position_event(event)))
            stage = "on_bar"
            raw.extend(_as_list(strategy.on_bar(primary)))
        except Exception as exc:
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
        signals, rejected = self._accept(raw, primary.close_time)
        return RunnerOutput(
            self.instance_id,
            symbol,
            primary.close_time,
            signals=tuple(signals),
            rejected=tuple(rejected),
            events=tuple(events),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    def submit_external(self, signal: Signal) -> RunnerOutput:
        """Apply a validated external (TradingView) signal to this instance's book."""
        signals, rejected = self._accept([signal], signal.timestamp)
        return RunnerOutput(
            self.instance_id,
            self.instrument.symbol,
            signal.timestamp,
            signals=tuple(signals),
            rejected=tuple(rejected),
        )

    # ── internals ───────────────────────────────────────────────────────────
    def _advance_book(self, bar: Bar) -> list[PositionEvent]:
        return self.book.on_bar(bar)

    def _accept(self, raw: list[Any], at: datetime) -> tuple[list[Signal], list[RejectedSignal]]:
        accepted: list[Signal] = []
        rejected: list[RejectedSignal] = []
        for item in raw:
            if not isinstance(item, Signal):
                rejected.append(self._reject(at, "NOT_A_SIGNAL", f"returned {type(item).__name__}"))
                continue
            mismatch = self._identity_mismatch(item)
            if mismatch:
                rejected.append(self._reject(at, "IDENTITY_MISMATCH", mismatch, item))
                continue
            try:
                validate_signal(item)
            except InvalidSignalError as exc:
                rejected.append(self._reject(at, exc.code, exc.message, item))
                continue
            self.book.apply(item)
            accepted.append(item)
        return accepted, rejected

    def _identity_mismatch(self, signal: Signal) -> str | None:
        expected = {
            "strategy_id": self.instance_id,
            "strategy_version": self.resolved.version,
            "symbol": self.instrument.symbol,
            "timeframe": self.resolved.timeframe.code,
        }
        for name, value in expected.items():
            if getattr(signal, name) != value:
                return f"{name} is {getattr(signal, name)!r}, expected {value!r}"
        return None

    def _reject(
        self, at: datetime, code: str, message: str, signal: Signal | None = None
    ) -> RejectedSignal:
        self.ctx.log.warning("strategy.signal_rejected", code=code, detail=message)
        return RejectedSignal(
            instance_id=self.instance_id,
            instrument=self.instrument.symbol,
            time=at,
            code=code,
            message=message,
            payload=signal.model_dump(mode="json") if signal is not None else {},
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


def _as_list(output: object) -> list[Any]:
    if output is None:
        return []
    if isinstance(output, Signal):
        return [output]
    if isinstance(output, (list, tuple)):
        return list(output)
    return [output]  # rejected later as NOT_A_SIGNAL

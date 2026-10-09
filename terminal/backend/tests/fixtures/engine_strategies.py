"""Strategies for the Phase 3 engine features (position rules, sessions, periods, lag).

Not registered globally; kept importable so the subprocess host could load them.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from kterminal.core.enums import OrderType
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.strategy_engine import (
    PositionEvent,
    SessionString,
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    TimeZoneName,
)
from kterminal.strategy_engine.base import NoParams


class Step(BaseModel):
    """One planned output: ``action`` on the ``bar``-th evaluated bar (1-based)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bar: int
    action: Literal["long", "short", "exit_long", "exit_short", "move_sl"]
    entry: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    order_type: OrderType = OrderType.MARKET
    session_close: bool = False


class PlanParams(StrategyParams):
    steps: tuple[Step, ...] = ()


class Planned(Strategy[PlanParams]):
    """Returns the planned signals in order and records every position event."""

    meta = StrategyMeta(id="planned", name="Planned", version="1.0.0", warmup_bars=0)
    Params = PlanParams

    def on_start(self) -> None:
        self.count = 0
        self.events: list[PositionEvent] = []

    def on_position_event(self, event: PositionEvent) -> SignalOutput:
        self.events.append(event)
        return None

    def on_bar(self, bar: Bar) -> SignalOutput:
        self.count += 1
        return [self._build(step) for step in self.params.steps if step.bar == self.count]

    def _build(self, step: Step) -> Signal:
        ctx = self.ctx
        if step.action == "exit_long":
            return ctx.exit_long(session_close=step.session_close)
        if step.action == "exit_short":
            return ctx.exit_short(session_close=step.session_close)
        if step.stop is None:
            raise ValueError(f"{step.action} needs a stop")
        if step.action == "move_sl":
            return ctx.move_sl(step.stop, take_profit=step.target)
        build = ctx.long if step.action == "long" else ctx.short
        return build(
            stop_loss=step.stop,
            take_profit=step.target,
            entry=step.entry,
            order_type=step.order_type,
        )


class Recorder(Strategy[NoParams]):
    """Records ``ctx.bar_index`` and the previous trading day on every bar (warm-up too)."""

    meta = StrategyMeta(id="recorder", name="Recorder", version="1.0.0", warmup_bars=0)
    Params = NoParams

    def on_start(self) -> None:
        self.indices: list[int] = []
        self.previous_day_high: list[Decimal | None] = []

    def on_bar(self, bar: Bar) -> SignalOutput:
        self.indices.append(self.ctx.bar_index)
        previous = self.ctx.periods.previous("D")
        self.previous_day_high.append(previous.high if previous is not None else None)
        return None


class WindowParams(StrategyParams):
    window: SessionString = "2000-0200"
    timezone: TimeZoneName = "America/New_York"


class WindowFlat(Strategy[WindowParams]):
    """Long on the first bar of the window, flat (SESSION_CLOSE) on its last bar."""

    meta = StrategyMeta(id="window_flat", name="Window flat", version="1.0.0", warmup_bars=0)
    Params = WindowParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        ctx, p = self.ctx, self.params
        if ctx.position is not None and ctx.session_ends(p.window, p.timezone):
            return ctx.exit_long(session_close=True)
        if ctx.position is None and ctx.session_started(p.window, p.timezone):
            return ctx.long(stop_loss=bar.close - 50)
        return None


class Idle(Strategy[NoParams]):
    """Does nothing: tests drive its runner and read the context."""

    meta = StrategyMeta(id="idle", name="Idle", version="1.0.0", warmup_bars=0)
    Params = NoParams

    def on_bar(self, bar: Bar) -> SignalOutput:
        return None


# A 1m scenario for ``Planned`` exercising every position rule: replace, a session-close
# exit, a market entry opening beyond its stop, a stop-out, an entry opening beyond its
# target, a reversal and a target. Levels keep clear of the lab cost profile's spread.
PLANNED_ROWS = [
    ("4000", "4001", "3999", "4000"),
    ("4000", "4001", "3999", "4000"),
    ("4002", "4003", "4001", "4002"),
    ("4002", "4003", "4001", "4003"),
    ("4003", "4004", "4002", "4003"),
    ("4012", "4013", "4011", "4012"),
    ("4011", "4012", "4010", "4011"),
    ("4011", "4035", "4010", "4030"),
    ("4041", "4042", "4040", "4041"),
    ("4041", "4042", "4040", "4041"),
    ("4040", "4041", "4039", "4040"),
    ("4035", "4036", "4019", "4020"),
]
PLANNED_STEPS: list[dict[str, Any]] = [
    {"bar": 1, "action": "long", "stop": "3990", "target": "4030"},
    {"bar": 2, "action": "exit_long"},  # replace …
    {"bar": 2, "action": "long", "stop": "3992", "target": "4025"},  # … on one bar
    {"bar": 4, "action": "exit_long", "session_close": True},
    {"bar": 5, "action": "short", "stop": "4010", "target": "3980"},  # opens beyond its stop
    {"bar": 6, "action": "short", "stop": "4030", "target": "3990"},  # stopped out
    {"bar": 8, "action": "long", "stop": "4020", "target": "4040"},  # opens beyond its target
    {"bar": 9, "action": "long", "stop": "4030", "target": "4060"},
    {"bar": 10, "action": "short", "stop": "4050", "target": "4020"},  # reverse, then target
]


def planned_minutes() -> list[Bar]:
    """XAUUSD 1m bars from Monday 2026-01-05 14:00 UTC (09:00 New York, metals open)."""
    start = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    return [
        Bar.of("XAUUSD", "1m", start + i * timedelta(minutes=1), o, h, low, c)
        for i, (o, h, low, c) in enumerate(PLANNED_ROWS)
    ]

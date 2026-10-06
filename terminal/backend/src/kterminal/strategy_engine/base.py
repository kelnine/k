"""The strategy SDK: what a strategy author writes against.

A strategy is a class with a :class:`StrategyMeta`, a frozen ``Params``
model and an ``on_bar`` method that returns zero or more
:class:`~kterminal.domain.signals.Signal` objects (built with the
``ctx.long/short/exit_long/exit_short/move_sl/no_trade`` helpers). It never
sizes positions, sees balances or places orders.

    class SmaParams(StrategyParams):
        fast: int = Field(9, ge=2)
        slow: int = Field(21, ge=3)

    @register_strategy
    class SmaCross(Strategy[SmaParams]):
        meta = StrategyMeta(id="sma_cross", name="SMA cross", version="1.0.0",
                            timeframes=("5m",), warmup_bars=50)
        Params = SmaParams

        def on_bar(self, bar):
            close = self.ctx.bars.close
            ...
            return self.ctx.long(stop_loss=..., take_profit=...)

Rules (see docs/05-strategy-interface.md): deterministic and pure (no I/O,
no wall clock, no unseeded randomness), closed bars only, no class-level
mutable state (rejected at registration), exceptions fault only this instance.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kterminal.core.enums import StrategyKind
from kterminal.domain.instruments import AssetClass
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.domain.timeframes import Timeframe
from kterminal.strategy_engine.model import PositionEvent

if TYPE_CHECKING:
    from kterminal.strategy_engine.context import StrategyContext

STRATEGY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")

SignalOutput = Signal | Sequence[Signal] | None


class StrategyParams(BaseModel):
    """Base class for strategy parameters: immutable and strict (typos are errors)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NoParams(StrategyParams):
    pass


class StrategyMeta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    version: str
    description: str = ""
    kind: StrategyKind = StrategyKind.INTERNAL
    timeframes: tuple[str, ...] = Field(
        default=(), description="Supported primary timeframes; empty = any"
    )
    context_timeframes: tuple[str, ...] = Field(
        default=(), description="Context timeframes the strategy always needs, e.g. ('15m', '1h')"
    )
    instruments: tuple[str, ...] | None = Field(
        default=None, description="Supported canonical instruments; None = any"
    )
    asset_classes: tuple[AssetClass, ...] | None = None
    sessions: tuple[str, ...] = Field(
        default=(),
        description="Session-window ids the strategy uses (validated against the catalog)",
    )
    warmup_bars: int = Field(default=200, ge=0, le=100_000)
    on_opposite_signal: Literal["reverse", "ignore"] = "reverse"
    max_pyramiding: int = Field(default=1, ge=1, le=1)  # pyramiding arrives with the risk engine
    tags: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not STRATEGY_ID_PATTERN.fullmatch(value):
            raise ValueError(f"strategy id {value!r} must match {STRATEGY_ID_PATTERN.pattern}")
        return value

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not SEMVER_PATTERN.fullmatch(value):
            raise ValueError(f"version {value!r} must be semantic (e.g. 1.0.0)")
        return value

    @field_validator("timeframes", "context_timeframes")
    @classmethod
    def _timeframes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(Timeframe.parse(tf).code for tf in value)


class Strategy[P: StrategyParams](ABC):
    """Base class of every internal (Python) strategy."""

    meta: ClassVar[StrategyMeta]
    Params: ClassVar[type[StrategyParams]] = NoParams

    def __init__(self, params: P, ctx: "StrategyContext") -> None:
        self.params: P = params
        self.ctx = ctx

    def on_start(self) -> None:  # noqa: B027 - optional hook
        """Called once before warm-up; initialise per-instance state here."""

    @abstractmethod
    def on_bar(self, bar: Bar) -> SignalOutput:
        """Called once per CLOSED primary-timeframe bar, in time order."""

    def on_position_event(self, event: PositionEvent) -> SignalOutput:
        """Theoretical position opened / closed / stop moved. Optional."""
        return None

    def on_stop(self) -> None:  # noqa: B027 - optional hook
        """Called on shutdown. Optional."""

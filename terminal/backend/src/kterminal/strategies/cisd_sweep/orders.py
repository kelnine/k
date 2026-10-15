"""How a CISD of script 1 becomes orders: doc 13 decisions D7, D4 and D3.

Script 1 prints an Entry at the CISD level, a stop at the run's extreme and TP1/TP2 at
1R/2R, but places no order and never checks a fill (spec "Parity risks"). Both of its
CISD models (``cisd_sweep``, ``cisd_scanner``) therefore share this base class, which
turns the model's signal into lab orders:

* **D7 entry** — ``entry: limit`` (default): a resting LIMIT at the CISD level with the
  script's stop and the chosen target, expiring after ``limit_expiry_bars`` (12)
  primary bars, and cancelled (an ``EXIT_*`` of the resting order) on the first bar
  after the signal bar on which TP1 trades while it is still unfilled
  (``cancel_on_tp1``). ``entry: market``: the comparison instance, filled at the next
  open with the script's absolute levels; doc 13 D3 skips it when the stop or target is
  not beyond the signal close (persisted ``NO_TRADE``) or the next open has passed
  either (``skip_entry_beyond_levels``, on in the meta).
* **D7 targets** — ``target: tp1`` or ``tp2``: one target per instance, no partial
  exits; the stop never moves (the script never moves it).
* **D4 replace** — the script overwrites its tracked trade with every new CISD (L721).
  A new CISD cancels the resting order and exits the open position at the next open,
  then enters (the engine's replace: both on one bar). In market mode an opposite CISD
  uses the engine's reverse instead (same fills, close reason ``REVERSAL``). A new CISD
  that cannot be traded (D3) still ends the old trade, as in the script.

Every signal carries the script's values in its metadata (``trigger`` = the script's
alert title, ``pine_signal``, ``script_entry/stop/tp1/tp2``, ``risk_points``) plus the
model's own explanation (sweep, run, body, levels).
"""

import math
from abc import abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import ClassVar, Literal

from pydantic import Field, JsonValue

from kterminal.core.enums import Direction, OrderType
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.indicators import na
from kterminal.strategy_engine import (
    PositionEvent,
    PositionEventKind,
    PositionView,
    SignalOutput,
    Strategy,
    StrategyParams,
)

EntryMode = Literal["limit", "market"]
TargetLeg = Literal["tp1", "tp2"]

NAN = math.nan


class CisdParams(StrategyParams):
    """The CISD inputs both models of script 1 share (Pine defaults and names, L84-94)
    and the doc 13 D7 order options."""

    req_sweep: bool = Field(True, description="reqSweep: require a liquidity sweep first")
    sweep_look: int = Field(
        12, ge=1, le=10_000, description="sweepLook: the sweep must be within this many bars"
    )
    min_body: float = Field(
        0.3,
        ge=0,
        le=100,
        allow_inf_nan=False,
        description="minBody: min CISD candle body as a multiple of ATR(14)",
    )
    tp1_r: float = Field(
        1.0, ge=0, le=100, allow_inf_nan=False, description="tp1R: TP 1 in R (0 = none)"
    )
    tp2_r: float = Field(
        2.0, ge=0, le=100, allow_inf_nan=False, description="tp2R: TP 2 in R (0 = none)"
    )
    entry: EntryMode = Field(
        "limit",
        description=(
            "D7: limit at the CISD level (the script's Entry), or market at the next open "
            "with the script's levels (comparison)"
        ),
    )
    target: TargetLeg = Field(
        "tp2", description="D7: the one target of this instance (TP1-only or TP2-only)"
    )
    limit_expiry_bars: int = Field(
        12, ge=1, le=10_000, description="D7: an unfilled limit expires after this many bars"
    )
    cancel_on_tp1: bool = Field(
        True, description="D7: cancel the unfilled limit when TP1 trades after the signal bar"
    )


@dataclass(frozen=True, slots=True)
class CisdSetup:
    """A CISD the model signalled on the evaluated bar (the script's trade projection)."""

    long: bool
    entry: float  # the CISD level: the open of the opposing run's first candle
    stop: float  # the run's extreme through the CISD bar
    trigger: str  # the script's alert title, e.g. "Bullish CISD"
    pine_signal: str  # the Pine variable, e.g. "bullCisd"
    metadata: dict[str, JsonValue] = field(default_factory=dict)


class CisdTradeStrategy[P: CisdParams](Strategy[P]):
    """D7 / D4 / D3 order handling around a CISD model (see the module docstring)."""

    MAX_TRACK_BARS: ClassVar[int | None] = None
    """Bars after its signal at which the script stops tracking a trade (None: never)."""

    # ── the model ─────────────────────────────────────────────────────────────
    @abstractmethod
    def _start_model(self) -> None:
        """Create the model's state (indicators, levels, runs)."""

    @abstractmethod
    def _evaluate(self, bar: Bar) -> CisdSetup | None:
        """Run the model on this bar (every bar, in order); the CISD it signals, if any."""

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def on_start(self) -> None:
        self._order: Signal | None = None  # our resting LIMIT, as far as the book reported
        self._order_bar = -1  # bar index of the signal that placed it
        self._order_tp1: Decimal | None = None  # its TP1 (the D7 cancel level)
        self._trade_bar: int | None = None  # bar index of the CISD behind the open position
        self._start_model()

    def on_position_event(self, event: PositionEvent) -> SignalOutput:
        if event.kind is PositionEventKind.OPENED:
            self._order = None
            bar_index = event.signal.metadata.get("bar_index") if event.signal else None
            self._trade_bar = bar_index if isinstance(bar_index, int) else None
        elif event.kind is PositionEventKind.CLOSED:
            self._trade_bar = None
        elif event.kind in (PositionEventKind.ORDER_EXPIRED, PositionEventKind.ORDER_CANCELLED):
            self._order = None
        return None

    def on_bar(self, bar: Bar) -> SignalOutput:
        setup = self._evaluate(bar)
        bar_index = self.ctx.bar_index
        if self._order is not None and bar_index - self._order_bar >= self.params.limit_expiry_bars:
            # The book expired it on this bar (ORDER_EXPIRED cleared it already), or it
            # never reached the book: an order placed during warm-up is discarded.
            self._order = None
        tp1_first = self._tp1_traded(bar)
        if setup is not None:
            return self._replace(setup, bar, tp1_first=tp1_first)
        out: list[Signal] = []
        if tp1_first:
            out.append(self._cancel("TP1 traded before the fill"))
        position = self.ctx.position
        limit = self.MAX_TRACK_BARS
        if (
            limit is not None
            and position is not None
            and self._trade_bar is not None
            and bar_index - self._trade_bar > limit
        ):
            out.append(self._time_exit(position, limit))
        return out

    # ── D4: a new CISD replaces the order or trade ────────────────────────────
    def _replace(self, setup: CisdSetup, bar: Bar, *, tp1_first: bool) -> list[Signal]:
        entry = self._entry(setup, bar)
        out: list[Signal] = []
        if self._order is not None:
            why = "TP1 traded before the fill" if tp1_first else "replaced by a new CISD"
            out.append(self._cancel(why))
        position = self.ctx.position
        if position is not None:
            # market mode, opposite direction: the engine reverses at the next open
            reverse = (
                self.params.entry == "market"
                and entry.signal.is_entry
                and position.is_long != setup.long
            )
            if not reverse:
                out.append(self._replaced_exit(position))
        out.append(entry)
        if entry.signal.is_entry and entry.order_type is OrderType.LIMIT:
            self._order = entry
            self._order_bar = self.ctx.bar_index
            tp1 = entry.metadata.get("script_tp1")
            self._order_tp1 = (
                self.ctx.instrument.round_price(Decimal(repr(tp1)))
                if isinstance(tp1, float)
                else None
            )
        return out

    def _entry(self, setup: CisdSetup, bar: Bar) -> Signal:
        """The order for a CISD (L730-736): entry at the level, stop at the run extreme,
        TP = entry ± R × tpR with R = |entry − stop|; or the D3 ``NO_TRADE``."""
        p = self.params
        ctx = self.ctx
        sign = 1.0 if setup.long else -1.0
        risk = abs(setup.entry - setup.stop)
        tp1 = setup.entry + sign * risk * p.tp1_r if risk > 0 and p.tp1_r > 0 else NAN
        tp2 = setup.entry + sign * risk * p.tp2_r if risk > 0 and p.tp2_r > 0 else NAN
        target = tp1 if p.target == "tp1" else tp2
        limit = p.entry == "limit"
        metadata: dict[str, JsonValue] = {
            "trigger": setup.trigger,
            "pine_signal": setup.pine_signal,
            **setup.metadata,
            "script_entry": _num(setup.entry),
            "script_stop": _num(setup.stop),
            "script_tp1": _num(tp1),
            "script_tp2": _num(tp2),
            "risk_points": _num(risk),
            "entry_mode": p.entry,
            "target_leg": p.target,
            "expires_after_bars": p.limit_expiry_bars if limit else None,
            "cancel_on_tp1": p.cancel_on_tp1 if limit else None,
            "bar_index": ctx.bar_index,
        }
        reference = setup.entry if limit else float(bar.close)
        problem = self._invalid_levels(setup.long, reference, setup.stop, target)
        if problem is not None:  # doc 13 D3
            return ctx.no_trade(problem, persist=True, metadata=metadata)
        build = ctx.long if setup.long else ctx.short
        take_profit = None if na(target) else target
        if limit:
            return build(
                entry=setup.entry,
                stop_loss=setup.stop,
                take_profit=take_profit,
                order_type=OrderType.LIMIT,
                expires_after_bars=p.limit_expiry_bars,
                reason=f"{setup.trigger}: limit at the CISD level",
                metadata=metadata,
            )
        return build(
            stop_loss=setup.stop,
            take_profit=take_profit,
            reason=f"{setup.trigger}: market at the next open",
            metadata=metadata,
        )

    def _invalid_levels(self, long: bool, entry: float, stop: float, target: float) -> str | None:
        """Why the levels cannot be traded after rounding to the tick, or None. The entry
        is the CISD level (limit) or the signal close (market); a na target is allowed
        (``tpR`` 0: no target)."""
        if na(entry) or na(stop):
            return "LEVELS_NA"
        if entry <= 0 or stop <= 0 or (not na(target) and target <= 0):
            return "LEVELS_NOT_POSITIVE"
        round_price = self.ctx.instrument.round_price
        e, s = round_price(Decimal(repr(entry))), round_price(Decimal(repr(stop)))
        if (s >= e) if long else (s <= e):
            return "STOP_WRONG_SIDE"
        if not na(target):
            t = round_price(Decimal(repr(target)))
            if (t <= e) if long else (t >= e):
                return "TARGET_WRONG_SIDE"
        return None

    # ── D7: the unfilled limit ────────────────────────────────────────────────
    def _tp1_traded(self, bar: Bar) -> bool:
        """Whether TP1 traded on this bar while the limit is still unfilled (the book
        tried this bar's fill already), from the bar after the signal bar on."""
        order, tp1 = self._order, self._order_tp1
        if order is None or tp1 is None or not self.params.cancel_on_tp1:
            return False
        if self.ctx.bar_index <= self._order_bar:
            return False
        if order.signal.direction is Direction.LONG:
            return bar.high >= tp1
        return bar.low <= tp1

    def _cancel(self, why: str) -> Signal:
        """An ``EXIT_*`` of the resting limit (book and account cancel it)."""
        order = self._order
        if order is None:  # pragma: no cover - callers check
            raise RuntimeError("no resting order to cancel")
        self._order = None
        metadata: dict[str, JsonValue] = {
            "trigger": "order cancelled",
            "detail": why,
            "order_entry": _text(order.entry),
            "order_tp1": _text(self._order_tp1),
            "order_bar_index": self._order_bar,
            "bar_index": self.ctx.bar_index,
        }
        long = order.signal.direction is Direction.LONG
        build = self.ctx.exit_long if long else self.ctx.exit_short
        return build(reason=f"cancel the CISD limit: {why}", metadata=metadata)

    # ── exits of the open position ────────────────────────────────────────────
    def _replaced_exit(self, position: PositionView) -> Signal:
        metadata: dict[str, JsonValue] = {
            "trigger": "trade replaced",
            "detail": "a new CISD replaces the tracked trade (L721); exit at the next open",
            "position_entry": _text(position.entry_price),
            "trade_bar_index": self._trade_bar,
            "bar_index": self.ctx.bar_index,
        }
        build = self.ctx.exit_long if position.is_long else self.ctx.exit_short
        return build(reason="replaced by a new CISD", metadata=metadata)

    def _time_exit(self, position: PositionView, limit: int) -> Signal:
        metadata: dict[str, JsonValue] = {
            "trigger": "tracking ended",
            "detail": f"the script stops tracking a trade {limit} bars after its signal",
            "position_entry": _text(position.entry_price),
            "trade_bar_index": self._trade_bar,
            "bar_index": self.ctx.bar_index,
        }
        self._trade_bar = None  # one exit; the position closes at the next open
        build = self.ctx.exit_long if position.is_long else self.ctx.exit_short
        return build(session_close=True, metadata=metadata)


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) else float(value)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)

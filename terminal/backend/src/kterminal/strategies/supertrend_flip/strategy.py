"""Jetstream v2 — SuperTrend (10, 3) flip, stop and reverse (doc 13, S7).

Port of the BUY/SELL and BUY+/SELL+ signals of
``terminal/pine/received/10_jetstream_v2.pine`` (spec:
``terminal/pine/specs/10_jetstream_v2.md``). Every closed bar:

* ``[st, dir] = ta.supertrend(3.0, 10)`` (L121) and ``flip = ta.change(dir)``
  (L166): BUY when ``flip < 0`` (direction 1 → −1), SELL when ``flip > 0``
  (L167-168); the HTF filter is off by default (L30), so ``buyOK``/``sellOK``
  are true;
* WaveTrend of ``hlc3`` (10, 21, 4) (L147-151): a BUY is "strong" (BUY+) while
  ``wt1 < 0``, a SELL (SELL+) while ``wt1 > 0`` (L169-170).

The script defines no stop or exit. Doc 13 D5 applies: the position exits (and
reverses) at the next open after the closed-candle flip; every entry carries a
protective stop at the SuperTrend line ∓ ``stop_atr_mult`` × ATR(10) of the
signal bar. ``signals: strong`` enters only on BUY+/SELL+ but still exits on
any opposite flip; ``trail_stop`` moves the stop onto the line every bar
(``MOVE_SL``, never widening). The README lists every deviation.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.indicators import Change, SuperTrend, WaveTrend, gt, lt, na
from kterminal.strategy_engine import (
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    register_strategy,
)


class SuperTrendFlipParams(StrategyParams):
    """The script's signal inputs (L26-27, L49-51; Pine defaults and names) and the
    doc 13 D5/D11 choices."""

    atr_len: int = Field(10, ge=1, le=1_000, description="atrLen: SuperTrend ATR length")
    mult: float = Field(3.0, ge=0.1, le=100, allow_inf_nan=False, description="mult: ATR factor")
    n1: int = Field(10, ge=1, le=1_000, description="WaveTrend channel length")
    n2: int = Field(21, ge=1, le=1_000, description="WaveTrend average length")
    sig_len: int = Field(4, ge=1, le=1_000, description="WaveTrend signal SMA (wt2)")
    signals: Literal["all", "strong"] = Field(
        "all", description="all: every BUY/SELL flip; strong: only BUY+/SELL+ (D11)"
    )
    stop_atr_mult: float = Field(
        1.0,
        ge=0,
        le=100,
        allow_inf_nan=False,
        description="protective stop = SuperTrend line -/+ this × ATR(atr_len) (D5)",
    )
    trail_stop: bool = Field(
        False, description="move the stop onto the line -/+ stop_atr_mult × ATR every bar (D5)"
    )


def flip_signals(flip: float, wt1: float) -> tuple[bool, bool, bool, bool]:
    """``(tBuy, tSell, strongBuy, strongSell)`` from ``ta.change(dir)`` and ``wt1``
    (L167-170, HTF filter off). Pine comparisons: na is false."""
    t_buy = lt(flip, 0.0)
    t_sell = gt(flip, 0.0)
    return t_buy, t_sell, t_buy and lt(wt1, 0.0), t_sell and gt(wt1, 0.0)


@register_strategy
class SuperTrendFlip(Strategy[SuperTrendFlipParams]):
    meta = StrategyMeta(
        id="supertrend_flip",
        name="Jetstream v2 · SuperTrend (10, 3) flip",
        version="1.0.0",
        description=(
            "Pine port of script 10 (Jetstream v2): stop and reverse on the closed-candle "
            "SuperTrend(10, 3) flip, BUY+/SELL+ (WaveTrend wt1 still beyond zero) as the "
            "strong-only variant; protective stop 1 ATR beyond the line or trailed on it. "
            "Doc 13 S7."
        ),
        warmup_bars=500,  # ATR(10), the ratcheting bands and WaveTrend settle (spec: >= 300)
        on_opposite_signal="reverse",  # doc 13 D4 for script 10
        skip_entry_beyond_levels=True,  # doc 13 D3: signals are priced at the bar close
        tags=("pine-port", "script-10", "s7"),
    )
    Params = SuperTrendFlipParams

    def on_start(self) -> None:
        p = self.params
        self._supertrend = SuperTrend(p.mult, p.atr_len)  # ta.supertrend(mult, atrLen) (L121)
        self._flip = Change(1)  # ta.change(dir) (L166)
        self._wavetrend = WaveTrend(p.n1, p.n2, p.sig_len)  # esa/de/ci/wt1/wt2 (L147-151)

    def on_bar(self, bar: Bar) -> SignalOutput:
        p = self.params
        ctx = self.ctx
        high, low, close = float(bar.high), float(bar.low), float(bar.close)
        line, direction = self._supertrend.update(high, low, close)
        atr = self._supertrend.atr
        flip = self._flip.update(float(direction))
        wt1, wt2 = self._wavetrend.update((high + low + close) / 3.0)  # src = hlc3 (L48)
        t_buy, t_sell, strong_buy, strong_sell = flip_signals(flip, wt1)

        position = ctx.position
        if not (t_buy or t_sell):
            if p.trail_stop and position is not None:
                return self._trail(line, direction, atr)
            return None

        is_buy = t_buy
        strong = strong_buy if is_buy else strong_sell
        trigger = ("BUY" if is_buy else "SELL") + ("+" if strong else "")
        metadata: dict[str, JsonValue] = {
            "pine_signal": _pine_name(is_buy, strong),
            "trigger": trigger,
            "strong": strong,
            "supertrend": _num(line),
            "direction": direction,
            "flip": _num(flip),
            "atr": _num(atr),
            "wt1": _num(wt1),
            "wt2": _num(wt2),
            "signals": p.signals,
            "bar_index": ctx.bar_index,
        }
        out: list[Signal] = []
        # D5: any closed-candle flip closes the opposite position at the next open,
        # whether or not the new side is traded (strong-only exits flat).
        if position is not None and (position.is_short if is_buy else position.is_long):
            reason = f"SuperTrend flip ({trigger})"
            exit_signal = ctx.exit_short if is_buy else ctx.exit_long
            out.append(exit_signal(reason=reason, metadata=metadata))
        if p.signals == "strong" and not strong:
            return out
        offset = p.stop_atr_mult * atr
        stop = line - offset if is_buy else line + offset
        entry_metadata: dict[str, JsonValue] = {
            **metadata,
            "script_entry": _num(close),
            "script_stop": _num(stop),
            "stop_atr_mult": p.stop_atr_mult,
            "trail_stop": p.trail_stop,
        }
        entry = ctx.instrument.round_price(bar.close)
        skip = _wrong_side(ctx.instrument.round_price, entry, stop, is_buy)
        if skip is not None:  # doc 13 D3: no trade with a stop on the wrong side
            out.append(ctx.no_trade(skip, persist=True, metadata=entry_metadata))
            return out
        build = ctx.long if is_buy else ctx.short
        out.append(build(stop_loss=stop, reason=f"Jetstream {trigger}", metadata=entry_metadata))
        return out

    def _trail(self, line: float, direction: int, atr: float) -> SignalOutput:
        """``MOVE_SL`` onto the line (∓ the ATR offset) when that tightens the stop."""
        position = self.ctx.position
        if position is None:
            return None
        # The line is on the position's side only while the trend agrees with it.
        if (direction != -1) if position.is_long else (direction != 1):
            return None
        offset = self.params.stop_atr_mult * atr
        level = line - offset if position.is_long else line + offset
        if na(level) or level <= 0:
            return None
        new_stop = self.ctx.instrument.round_price(Decimal(repr(level)))
        current = position.stop_loss
        if not (new_stop > current if position.is_long else new_stop < current):
            return None
        return self.ctx.move_sl(
            new_stop,
            reason="SuperTrend trail",
            metadata={"supertrend": _num(line), "atr": _num(atr), "direction": direction},
        )


def _wrong_side(
    round_price: Callable[[Decimal], Decimal], entry: Decimal, stop: float, is_long: bool
) -> str | None:
    """Why the protective stop cannot be traded after rounding to the tick, or None."""
    if na(stop):
        return "STOP_NA"
    if stop <= 0:
        return "STOP_NOT_POSITIVE"
    rounded = round_price(Decimal(repr(stop)))
    if (rounded >= entry) if is_long else (rounded <= entry):
        return "STOP_WRONG_SIDE"
    return None


def _pine_name(is_buy: bool, strong: bool) -> str:
    if strong:
        return "strongBuy" if is_buy else "strongSell"
    return "tBuy" if is_buy else "tSell"


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) else float(value)

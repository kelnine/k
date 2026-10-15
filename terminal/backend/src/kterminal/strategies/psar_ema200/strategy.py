"""Combined SMC Suite — 200 EMA filtered Parabolic SAR (doc 13, S8).

Port of the PSAR section (L563-638) of
``terminal/pine/received/04_combined_smc_suite.pine`` (spec:
``terminal/pine/specs/04_combined_smc_suite.md``). The script's author rebuilt
this section from screenshots of the original's settings panel (L7-8). Every
closed bar:

* ``psSar = ta.sar(0.02, 0.02, 0.2)``, ``psSlow = ta.ema(close, 200)`` and the
  ADX of ``ta.dmi(14, 14)`` (L602-605);
* the flip is the SAR crossing the close: ``psFlipUp = psSar < close`` and not
  so on the previous bar (L607-611), not the SAR's internal trend;
* the script's own state ``psInLong``/``psInShort`` (L617-638): an open side
  exits on the opposite flip regardless of the filters (L621-627); a long opens
  only on a flip-up bar with ``close > EMA200`` and ``ADX > 20`` (strict) and
  not already long (L630), a short mirrors it (L631). So a flip reverses only
  when the new side's filters pass, otherwise the script is flat.

The script defines no stop. Doc 13 D5 applies: the position exits at the next
open after the close-confirmed flip; the protective stop is fixed at the SAR
printed on the signal bar (``stop_mode: sar``) or trailed every bar on
TradingView's projected SAR, the level whose touch flips the next bar
(``stop_mode: trail``, ``MOVE_SL``, never widening). The README lists every
deviation.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue

from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.indicators import Dmi, Ema, Sar, gt, lt, na
from kterminal.strategy_engine import (
    SignalOutput,
    Strategy,
    StrategyMeta,
    StrategyParams,
    register_strategy,
)


class PsarEma200Params(StrategyParams):
    """The section's inputs that change signals (L573-581; Pine defaults and names) and
    the doc 13 D5 stop choice. MaFast/MaMed (7/21) only colour a band and are omitted."""

    ma_slow_length: int = Field(200, ge=1, le=5_000, description="psMaSlowLength: trend EMA")
    psar_start: float = Field(0.02, gt=0, le=1, allow_inf_nan=False, description="psStart")
    increment: float = Field(0.02, ge=0, le=1, allow_inf_nan=False, description="psIncrement")
    maximum: float = Field(0.2, gt=0, le=1, allow_inf_nan=False, description="psMaximum")
    adx_smoothing: int = Field(14, ge=1, le=1_000, description="psAdxSmoothing")
    di_length: int = Field(14, ge=1, le=1_000, description="psDiLength")
    threshold: int = Field(20, ge=0, le=100, description="psThreshold: ADX must be above it")
    stop_mode: Literal["sar", "trail"] = Field(
        "sar",
        description=(
            "sar: stop fixed at the SAR printed on the signal bar; trail: stop on the "
            "projected SAR, moved every bar (D5)"
        ),
    )


class PsarState:
    """The script's flip detection and ``var bool psInLong/psInShort`` (L607-638).

    ``update`` takes the bar's SAR, close, EMA and ADX and returns
    ``(psLong, psShort, psExitLong, psExitShort)``. Comparisons are Pine's (1e-10
    tolerance, na is false); ``psSarBull[1]`` is false before the first bar, as a
    Pine v6 bool history is.
    """

    __slots__ = ("in_long", "in_short", "previous_bear", "previous_bull")

    def __init__(self) -> None:
        self.in_long = False
        self.in_short = False
        self.previous_bull = False
        self.previous_bear = False

    def update(
        self, sar: float, close: float, ema: float, adx: float, threshold: float
    ) -> tuple[bool, bool, bool, bool]:
        sar_bull = lt(sar, close)  # psSarBull = psSar < close (L607)
        sar_bear = gt(sar, close)  # psSarBear = psSar > close (L608)
        flip_up = sar_bull and not self.previous_bull  # L610
        flip_down = sar_bear and not self.previous_bear  # L611
        self.previous_bull, self.previous_bear = sar_bull, sar_bear
        trend_up = gt(close, ema)  # L613
        trend_down = lt(close, ema)  # L614
        strong = gt(adx, threshold)  # L615
        exit_long = self.in_long and flip_down  # L621
        exit_short = self.in_short and flip_up  # L622
        if exit_long:
            self.in_long = False
        if exit_short:
            self.in_short = False
        go_long = flip_up and trend_up and strong and not self.in_long  # L630
        go_short = flip_down and trend_down and strong and not self.in_short  # L631
        if go_long:
            self.in_long, self.in_short = True, False
        if go_short:
            self.in_short, self.in_long = True, False
        return go_long, go_short, exit_long, exit_short


@register_strategy
class PsarEma200(Strategy[PsarEma200Params]):
    meta = StrategyMeta(
        id="psar_ema200",
        name="SMC Suite · 200 EMA filtered Parabolic SAR",
        version="1.0.0",
        description=(
            "Pine port of script 4's PSAR section: enter on the close-confirmed SAR flip "
            "with close beyond the EMA200 and ADX(14, 14) > 20, exit on the opposite flip, "
            "reverse only if the new side's filters pass; stop at the signal bar's SAR or "
            "trailed on the projected SAR. Doc 13 S8."
        ),
        warmup_bars=1_000,  # EMA200 and the Wilder DMI/ADX converge (spec: >= 1000)
        on_opposite_signal="reverse",  # doc 13 D4 for script 4
        skip_entry_beyond_levels=True,  # doc 13 D3: signals are priced at the bar close
        tags=("pine-port", "script-4", "s8"),
    )
    Params = PsarEma200Params

    def on_start(self) -> None:
        p = self.params
        self._ema = Ema(p.ma_slow_length)  # psSlow (L602)
        self._sar = Sar(p.psar_start, p.increment, p.maximum)  # psSar (L603)
        self._dmi = Dmi(p.di_length, p.adx_smoothing)  # ta.dmi (L605)
        self._state = PsarState()

    def on_bar(self, bar: Bar) -> SignalOutput:
        p = self.params
        ctx = self.ctx
        high, low, close = float(bar.high), float(bar.low), float(bar.close)
        ema = self._ema.update(close)
        sar = self._sar.update(high, low, close)
        adx = self._dmi.update(high, low, close).adx
        go_long, go_short, exit_long, exit_short = self._state.update(
            sar, close, ema, adx, float(p.threshold)
        )
        projected = self._sar.projected()
        position = ctx.position
        if not (go_long or go_short or exit_long or exit_short):
            if p.stop_mode == "trail" and position is not None:
                return self._trail(projected)
            return None

        metadata: dict[str, JsonValue] = {
            "sar": _num(sar),
            "projected_sar": _num(projected),
            "sar_is_long": self._sar.is_long,
            "ema": _num(ema),
            "adx": _num(adx),
            "close": _num(close),
            "bar_index": ctx.bar_index,
        }
        out: list[Signal] = []
        # Exits ignore the filters (L621-627) and come before the new side, so a
        # reversal is "exit, then enter" on the same next open (doc 05 §5.3 replace).
        if exit_long and position is not None and position.is_long:
            out.append(ctx.exit_long(reason="PSAR exit long", metadata=_named(metadata, "EL")))
        if exit_short and position is not None and position.is_short:
            out.append(ctx.exit_short(reason="PSAR exit short", metadata=_named(metadata, "ES")))
        if go_long or go_short:
            out.append(self._entry(bar, go_long, sar, projected, metadata))
        return out

    def _entry(
        self,
        bar: Bar,
        is_long: bool,
        sar: float,
        projected: float,
        metadata: dict[str, JsonValue],
    ) -> Signal:
        ctx = self.ctx
        trail = self.params.stop_mode == "trail"
        stop = projected if trail else sar
        entry_metadata = {
            **_named(metadata, "Long" if is_long else "Short"),
            "stop_mode": self.params.stop_mode,
            "script_entry": _num(float(bar.close)),
            "script_stop": _num(stop),
        }
        entry = ctx.instrument.round_price(bar.close)
        skip = _wrong_side(ctx.instrument.round_price, entry, stop, is_long)
        if skip is not None:  # doc 13 D3: no trade with a stop on the wrong side
            return ctx.no_trade(skip, persist=True, metadata=entry_metadata)
        build = ctx.long if is_long else ctx.short
        reason = "PSAR long — 200 EMA filtered" if is_long else "PSAR short — 200 EMA filtered"
        return build(stop_loss=stop, reason=reason, metadata=entry_metadata)

    def _trail(self, projected: float) -> SignalOutput:
        """``MOVE_SL`` to the projected SAR when that tightens the stop and the SAR is on
        the position's side (a reversed SAR has already taken the trailed stop out)."""
        position = self.ctx.position
        if position is None or self._sar.is_long is not position.is_long:
            return None
        if na(projected) or projected <= 0:
            return None
        new_stop = self.ctx.instrument.round_price(Decimal(repr(projected)))
        tighter = new_stop > position.stop_loss if position.is_long else new_stop < position.stop_loss
        if not tighter:
            return None
        return self.ctx.move_sl(
            new_stop, reason="PSAR trail", metadata={"projected_sar": _num(projected)}
        )


def _named(metadata: dict[str, JsonValue], trigger: str) -> dict[str, JsonValue]:
    """Metadata with the script's marker text (L1044-1047) and Pine variable."""
    pine = {"Long": "psLong", "Short": "psShort", "EL": "psExitLong", "ES": "psExitShort"}
    return {**metadata, "trigger": trigger, "pine_signal": pine[trigger]}


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


def _num(value: float) -> float | None:
    """A float for JSON metadata: na becomes null."""
    return None if na(value) else float(value)

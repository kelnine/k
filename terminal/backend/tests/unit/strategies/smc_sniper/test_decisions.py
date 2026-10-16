"""The doc 13 decisions applied to the sniper: D3 (levels from the signal close, gap
guard, no trade on a wrong-side stop), D4 (ignore while in a trade), and the params."""

import pytest
from pydantic import ValidationError

from kterminal.core.enums import Direction, SignalAction
from kterminal.strategies.smc_sniper import SmcSniper, SmcSniperParams
from kterminal.strategy_engine import CloseReason, InstanceSpec, PositionEventKind
from kterminal.strategy_engine.registry import definition_from_class
from tests.unit.strategies.pine_port_support import (
    actions,
    entries,
    index_of,
    make_bars,
    of_kind,
    positions_at_decisions,
    run,
)
from tests.unit.strategies.smc_sniper.scenarios import (
    BASE,
    SHORT_LENGTHS,
    SIGNAL_BAR,
    WRONG_SIDE,
    Row,
)
from tests.unit.strategies.smc_sniper.test_rules import sniper

NO_TRADE = SignalAction.NO_TRADE


def test_definition_rules_are_ignore_and_the_gap_guard() -> None:
    meta = definition_from_class(SmcSniper).meta
    assert meta.on_opposite_signal == "ignore"  # D4 for script 5
    assert meta.skip_entry_beyond_levels is True  # D3
    assert meta.warmup_bars == 1_000


def test_wrong_side_stops_are_not_traded() -> None:
    # Bar 25: the crash breaks the swing low 111.0 (a CHoCH) but the short's stop is the
    # stale swing high 102 + 0.5 ATR, below the close 105. Bar 27: the rebound breaks 102
    # and the long's stop is 111 − 0.5 ATR, above the close 103.5. The script would
    # draw both labels (with SL and TP swapped); the lab records NO_TRADE.
    result = sniper(WRONG_SIDE, sniper_min=1)
    assert actions(result) == [(12, NO_TRADE), (25, NO_TRADE), (27, NO_TRADE)]
    _, short, long = result.signals
    assert short.reason == "STOP_WRONG_SIDE" and short.persist is True
    assert short.metadata["pine_signal"] == "sniper_short"
    assert short.metadata["structure_label"] == "CHoCH"
    assert short.metadata["stop_basis"] == "swing_high" and short.metadata["lsh"] == 102.0
    stop = short.metadata["script_stop"]
    assert isinstance(stop, float) and stop < 105.0
    assert long.reason == "STOP_WRONG_SIDE"
    assert long.metadata["pine_signal"] == "sniper_long"
    assert long.metadata["structure_label"] == "CHoCH"  # upt was cleared on bar 25
    assert long.metadata["stop_basis"] == "swing_low" and long.metadata["lsl"] == 111.0
    stop = long.metadata["script_stop"]
    assert isinstance(stop, float) and stop > 103.5
    assert result.events == []


def test_a_signal_while_the_atr_is_na_is_not_traded() -> None:
    # Bar 12 breaks the swing high 102 while ATR(14) is still na: the script's SL/TP
    # would be na (its label reads NaN). Recorded as NO_TRADE LEVELS_NA.
    first = sniper(WRONG_SIDE, sniper_min=1).signals[0]
    assert index_of(first) == 12
    assert first.reason == "LEVELS_NA"
    assert first.metadata["atr"] is None and first.metadata["script_stop"] is None


def test_the_entry_fills_at_the_next_open_with_the_script_levels() -> None:
    rows = [*BASE, (108.9, 109.2, 108.7, 109.1)]
    result = sniper(rows)
    [signal] = entries(result)
    [opened] = of_kind(result, PositionEventKind.OPENED)
    assert float(signal.entry or 0) == 108.8  # the signal close, the script's price
    assert float(opened.price or 0) == 108.9  # filled at bar 24's open
    assert opened.signal is not None and opened.signal.stop_loss == signal.stop_loss


@pytest.mark.parametrize(
    ("fill_bar", "detail"),
    [
        ((112.0, 112.5, 111.8, 112.2), "OPEN_BEYOND_TARGET"),  # target 111.94
        ((107.0, 107.5, 106.8, 107.2), "OPEN_BEYOND_STOP"),  # stop 107.23
    ],
)
def test_gap_guard_skips_a_fill_beyond_the_levels(fill_bar: Row, detail: str) -> None:
    result = sniper([*BASE, fill_bar])
    [cancelled] = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert cancelled.detail == detail
    assert of_kind(result, PositionEventKind.OPENED) == []


def test_a_new_signal_while_in_a_trade_is_ignored() -> None:
    # The second BOS of the same level (bar 25) is emitted — the script draws it — but
    # the long from bar 23 is still open, so the book (and every account) ignores it.
    rows = [
        *BASE,
        (108.8, 108.9, 108.3, 108.4),  # 24: the fill bar
        (108.4, 109.0, 108.3, 108.9),  # 25: re-cross of 108.6
        (108.9, 109.3, 108.8, 109.2),  # 26
    ]
    result = sniper(rows)
    assert actions(result) == [(23, SignalAction.LONG), (25, SignalAction.LONG)]
    bars = make_bars(rows)
    held = positions_at_decisions(bars, result.events)
    assert held[25] is Direction.LONG
    assert len(of_kind(result, PositionEventKind.OPENED)) == 1
    [opened] = of_kind(result, PositionEventKind.OPENED)
    assert opened.signal is not None and index_of(opened.signal) == SIGNAL_BAR


def test_the_trade_ends_only_at_its_stop_or_target() -> None:
    rows = [*BASE, (108.9, 109.2, 108.7, 109.1), (109.1, 112.5, 109.0, 112.3)]
    result = sniper(rows)
    [closed] = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.TAKE_PROFIT
    assert float(closed.price or 0) == 111.94
    assert [s for s in result.signals if s.signal.is_exit] == []


def test_params_mirror_the_script_inputs_and_are_strict() -> None:
    p = SmcSniperParams()
    assert (p.sniper_min, p.fvg_on, p.fvg_max, p.ob_on, p.ob_len, p.ob_max) == (
        3,
        True,
        4,
        True,
        10,
        3,
    )
    assert (p.bos_len, p.smb_atr) == (40, 14)
    with pytest.raises(ValidationError, match="sniper_min"):
        SmcSniperParams(sniper_min=5)
    with pytest.raises(ValidationError, match="bos_len"):
        SmcSniperParams(bos_len=4)  # Pine minval 5
    with pytest.raises(ValidationError, match="ob_len"):
        SmcSniperParams(ob_len=2)  # Pine minval 3
    with pytest.raises(ValidationError, match="fvg_max"):
        SmcSniperParams(fvg_max=9)
    with pytest.raises(ValidationError, match="bos_on"):
        SmcSniperParams.model_validate({"bos_on": False})  # not a param: off = no signals
    InstanceSpec(id="x_smc", strategy="smc_sniper", instruments=("XAUUSD",), timeframe="15m")


def test_short_lengths_are_only_a_test_device() -> None:
    assert SHORT_LENGTHS == {"bos_len": 5, "ob_len": 3}  # the inputs' Pine minimums
    result = run(SmcSniper, make_bars(BASE), params=SHORT_LENGTHS)
    assert [s.signal for s in result.signals] == [SignalAction.LONG]
    assert run(SmcSniper, make_bars(BASE)).signals == []  # 40/40 swings need more bars

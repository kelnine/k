import pytest

from kterminal.core.enums import Direction, OrderSide, SignalAction, TradingMode


def test_only_live_risks_real_money() -> None:
    assert [m for m in TradingMode if m.risks_real_money] == [TradingMode.LIVE]
    assert {m for m in TradingMode if m.uses_broker_api} == {TradingMode.DEMO, TradingMode.LIVE}


@pytest.mark.parametrize(
    ("action", "is_entry", "is_exit", "direction"),
    [
        (SignalAction.LONG, True, False, Direction.LONG),
        (SignalAction.SHORT, True, False, Direction.SHORT),
        (SignalAction.EXIT_LONG, False, True, Direction.LONG),
        (SignalAction.EXIT_SHORT, False, True, Direction.SHORT),
        (SignalAction.MOVE_SL, False, False, None),
        (SignalAction.NO_TRADE, False, False, None),
    ],
)
def test_signal_action_semantics(
    action: SignalAction, is_entry: bool, is_exit: bool, direction: Direction | None
) -> None:
    assert action.is_entry is is_entry
    assert action.is_exit is is_exit
    assert action.direction is direction


def test_signal_actions_match_the_specified_set() -> None:
    assert [a.value for a in SignalAction] == [
        "LONG",
        "SHORT",
        "EXIT_LONG",
        "EXIT_SHORT",
        "MOVE_SL",
        "NO_TRADE",
    ]


def test_direction_sides() -> None:
    assert Direction.LONG.entry_side is OrderSide.BUY
    assert Direction.LONG.exit_side is OrderSide.SELL
    assert Direction.SHORT.entry_side is OrderSide.SELL
    assert Direction.SHORT.exit_side is OrderSide.BUY
    assert Direction.LONG.opposite is Direction.SHORT


def test_enums_serialize_as_plain_strings() -> None:
    assert f"{TradingMode.PAPER}" == "PAPER"
    assert SignalAction("MOVE_SL") is SignalAction.MOVE_SL

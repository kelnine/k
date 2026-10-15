"""The doc 13 decisions the script leaves open: D3 (gap guard), D4 (ignore while in a
trade), D5 (stop, target, flat at 16:00, no fill at or after it) and its variants."""

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from kterminal.core.enums import Direction, SignalAction
from kterminal.strategies.orb_breakout import OrbBreakout, OrbParams
from kterminal.strategy_engine import CloseReason, InstanceSpec, PositionEventKind
from kterminal.strategy_engine.registry import definition_from_class
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.unit.strategies.orb_breakout.helpers import (
    at,
    day_bars,
    hhmm,
    local,
    run,
    strategy_object,
)
from tests.unit.strategies.orb_breakout.test_rules import NO_FILTER, OR_ROWS, TUE, WED
from tests.unit.strategies.pine_port_support import (
    dumps,
    entries,
    of_kind,
    positions_at_decisions,
)

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT
LONG_0945 = {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6)}


def test_flat_at_1600_exit_decided_on_the_1555_bar() -> None:
    result = run(day_bars(TUE, LONG_0945), params=NO_FILTER)
    exits = [s for s in result.signals if s.signal is SignalAction.EXIT_LONG]
    assert at(exits) == [("15:55", SignalAction.EXIT_LONG)]
    assert exits[0].reason == "SESSION_CLOSE"
    [closed] = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.SESSION_CLOSE
    assert hhmm(closed.time) == "16:00"  # at the 16:00 bar's open
    assert float(closed.price or 0) == 101.6


def test_short_is_flattened_too() -> None:
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 100.1, 98.5, 98.9)})
    result = run(bars, params=NO_FILTER)
    assert at([s for s in result.signals if s.signal.is_exit]) == [
        ("15:55", SignalAction.EXIT_SHORT)
    ]
    [closed] = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.SESSION_CLOSE


def test_flatten_after_a_data_gap_exits_on_the_first_bar_past_1600() -> None:
    # No 15:55 bar: the 15:50 bar ends at 15:55 (before 16:00), so the exit is decided on
    # the 16:00 bar, the first that ends after the flatten time.
    result = run(day_bars(TUE, LONG_0945, skip=("15:55",)), params=NO_FILTER)
    exits = [s for s in result.signals if s.signal.is_exit]
    assert at(exits) == [("16:00", SignalAction.EXIT_LONG)]


def test_no_exit_when_the_stop_or_target_closed_the_trade_first() -> None:
    bars = day_bars(TUE, {**LONG_0945, "11:00": (101.6, 107, 101.6, 106.9)})
    result = run(bars, params=NO_FILTER)
    assert [s for s in result.signals if s.signal.is_exit] == []
    [closed] = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.TAKE_PROFIT
    assert float(closed.price or 0) == 106.8


def test_signal_whose_fill_lands_at_or_after_1600_is_skipped_but_consumed() -> None:
    # The script marks the 15:55 bar (closing at 16:00); the next-open fill would be at
    # 16:00, so no entry: a recorded NO_TRADE, and the day's long is used up.
    bars = day_bars(TUE, {**OR_ROWS, "15:55": (100, 102, 100, 101.9)})
    result = run(bars, params=NO_FILTER)
    assert entries(result) == []
    [skipped] = result.signals
    assert skipped.signal is SignalAction.NO_TRADE
    assert skipped.reason == "FILL_AT_OR_AFTER_FLATTEN"
    assert skipped.persist is True
    assert skipped.metadata["trigger"] == "ORB long"
    assert at([skipped]) == [("15:55", SignalAction.NO_TRADE)]
    current = strategy_object(result)._range
    assert current is not None and current.long_done and not current.short_done


def test_signal_on_the_1550_bar_still_trades_and_is_flattened_next_bar() -> None:
    bars = day_bars(TUE, {**OR_ROWS, "15:50": (100, 102, 100, 101.9)})
    result = run(bars, params=NO_FILTER)
    assert at(result.signals) == [("15:50", SignalAction.LONG), ("15:55", SignalAction.EXIT_LONG)]
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert [c.reason for c in closed] == [CloseReason.SESSION_CLOSE]


def test_gap_guard_skips_a_fill_that_opens_beyond_the_target() -> None:
    bars = day_bars(TUE, {**LONG_0945, "09:50": (107, 107.5, 106.5, 107)})
    result = run(bars, params=NO_FILTER)
    [cancelled] = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert cancelled.detail == "OPEN_BEYOND_TARGET"
    assert of_kind(result, PositionEventKind.OPENED) == []


def test_gap_guard_skips_a_fill_that_opens_at_or_beyond_the_stop() -> None:
    bars = day_bars(TUE, {**LONG_0945, "09:50": (99, 99.5, 98.5, 99)})
    result = run(bars, params=NO_FILTER)
    [cancelled] = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert cancelled.detail == "OPEN_BEYOND_STOP"


@pytest.mark.parametrize(
    ("target_r", "target"),
    [("1", 101.6 + 1.35), ("1.5", 101.6 + 1.5 * 1.35), (None, None)],
)
def test_midpoint_stop_variants(target_r: str | None, target: float | None) -> None:
    params = {**NO_FILTER, "stop_mode": "midpoint", "target_r": target_r}
    [signal] = entries(run(day_bars(TUE, LONG_0945), params=params))
    assert float(signal.stop_loss or 0) == 100.25  # (101.5 + 99) / 2
    if target is None:
        assert signal.take_profit is None
    else:
        assert float(signal.take_profit or 0) == pytest.approx(target, abs=0.005)
    assert signal.metadata["stop_mode"] == "midpoint"


def test_midpoint_rounds_to_the_tick_ties_away_from_zero() -> None:
    rows = {
        "09:30": (100, 101.01, 100, 101),
        "09:35": (101, 101.01, 100, 100.5),
        "09:45": (100.5, 101.5, 100.5, 101.2),
    }
    [signal] = entries(run(day_bars(TUE, rows), params={**NO_FILTER, "stop_mode": "midpoint"}))
    assert str(signal.stop_loss) == "100.51"  # math.avg = 100.505 → round_to_mintick


def test_no_target_variant_closes_only_at_the_flatten() -> None:
    bars = day_bars(TUE, {**LONG_0945, "11:00": (101.6, 120, 101.6, 119)})
    result = run(bars, params={**NO_FILTER, "stop_mode": "midpoint", "target_r": None})
    [closed] = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.SESSION_CLOSE
    assert float(closed.price or 0) == 119


def test_ignore_while_in_a_trade_is_the_definition_rule() -> None:
    meta = definition_from_class(OrbBreakout).meta
    assert meta.on_opposite_signal == "ignore"  # D4
    assert meta.skip_entry_beyond_levels is True  # D3


def test_flatten_time_param_is_validated_and_normalised() -> None:
    assert OrbParams(flatten_time="9:05").flatten_time == "09:05"
    with pytest.raises(ValueError, match="flatten_time"):
        OrbParams(flatten_time="25:00")
    with pytest.raises(ValueError, match="flatten_time"):
        OrbParams(flatten_time="noon")


def test_params_mirror_the_script_inputs_and_are_strict() -> None:
    p = OrbParams()
    assert (p.timezone, p.or_session, p.levels_session) == (
        "America/New_York",
        "0930-0945:1234567",
        "0930-1600:1234567",
    )
    assert (p.or_filter, p.fast_length, p.slow_length) == (True, 9, 20)
    assert (p.stop_mode, str(p.target_r), p.flatten_time) == ("range", "2", "16:00")
    with pytest.raises(ValidationError, match="stop_mode"):
        OrbParams(stop_mode="atr")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="target_r"):
        OrbParams.model_validate({"target_r": 0})
    with pytest.raises(ValidationError, match="or_session"):
        OrbParams(or_session="9:30-9:45")
    with pytest.raises(ValidationError, match="timezone"):
        OrbParams(timezone="Mars/Olympus")
    with pytest.raises(ValidationError, match="unknown"):
        OrbParams(unknown=1)  # type: ignore[call-arg]
    InstanceSpec(id="x_orb", strategy="orb_breakout", instruments=("MNQ",), timeframe="5m")


def test_position_direction_of_the_flatten_matches_the_trade() -> None:
    result = run(day_bars(TUE, LONG_0945), params=NO_FILTER)
    [opened] = of_kind(result, PositionEventKind.OPENED)
    assert opened.direction is Direction.LONG


def test_a_fill_delayed_past_the_flatten_by_a_data_gap_is_closed_at_once() -> None:
    # Signal on the 15:50 bar (its fill would be at 15:55), then no bars until Wednesday
    # 09:30: the long fills at Wednesday's first open and is closed on that same bar's
    # decision — the deadline is the signal day's 16:00, not the fill day's.
    bars = day_bars(TUE, {**OR_ROWS, "15:50": (100, 102, 100, 101.9)}, end="15:55")
    bars += day_bars(WED, {}, start="09:30", price=101.9)
    result = run(bars, params=NO_FILTER)
    [opened] = of_kind(result, PositionEventKind.OPENED)
    assert opened.time == local(WED, "09:30")
    exits = [s for s in result.signals if s.signal.is_exit]
    assert [(s.bar_time, s.signal) for s in exits] == [
        (local(WED, "09:30"), SignalAction.EXIT_LONG)
    ]
    assert exits[0].metadata["flatten_at"] == local(TUE, "16:00").isoformat()
    [closed] = of_kind(result, PositionEventKind.CLOSED)
    assert closed.reason is CloseReason.SESSION_CLOSE
    assert closed.time == local(WED, "09:35")


def test_a_window_past_midnight_flattens_on_the_next_day() -> None:
    # An evening range (20:00-20:15) whose levels run to 02:00 and flatten at 02:00: the
    # deadline is the first 02:00 after the signal, so the trade is held over midnight.
    params = {
        **NO_FILTER,
        "or_session": "2000-2015",
        "levels_session": "2000-0200",
        "flatten_time": "02:00",
    }
    rows = {
        "20:00": (100, 101, 99.5, 100.5),
        "20:05": (100.5, 101.5, 100, 101),
        "20:10": (101, 101.2, 99, 100),
        "20:15": (100, 101.8, 99.9, 101.6),
    }
    bars = day_bars(TUE, rows, start="18:00", end="23:55")
    bars += day_bars(WED, {}, start="00:00", end="03:00", price=101.6)
    result = run(bars, params=params)
    [signal] = entries(result)
    assert at([signal]) == [("20:15", SignalAction.LONG)]
    assert signal.metadata["flatten_at"] == local(WED, "02:00").isoformat()
    exits = [s for s in result.signals if s.signal.is_exit]
    assert [(s.bar_time, s.signal) for s in exits] == [
        (local(WED, "01:55"), SignalAction.EXIT_LONG)
    ]
    assert strategy_object(result).flatten_deadline(local(TUE, "20:15")) == local(WED, "02:00")


def test_flatten_deadline_follows_the_clock_change() -> None:
    # 16:00 New York is 21:00 UTC in winter and 20:00 UTC in summer.
    strategy = strategy_object(run(day_bars(TUE, {})))
    assert strategy.flatten_deadline(local(TUE, "10:00")).hour == 21
    summer = local(date(2026, 7, 15), "10:00")
    assert strategy.flatten_deadline(summer).hour == 20
    assert strategy.flatten_deadline(local(TUE, "16:00")) == local(TUE, "16:00")


def test_opposite_signal_policy_never_changes_a_trade_with_these_stops() -> None:
    # D4 (ignore) is the definition rule, but with the stop on the other side of the
    # range (or at its midpoint) the opposite breakout can only close beyond that stop,
    # so the trade is already stopped out when the opposite signal is decided.
    rows = {**LONG_0945, "10:30": (101.6, 101.6, 98.0, 98.5)}
    bars = day_bars(TUE, rows)
    for stop_mode in ("range", "midpoint"):
        params = {**NO_FILTER, "stop_mode": stop_mode}
        ignore = run(bars, params=params)
        reverse = run(bars, params=params, on_opposite_signal="reverse")
        assert at(entries(ignore)) == [("09:45", LONG), ("10:30", SHORT)]
        held = positions_at_decisions(bars, ignore.events)
        short_bar = next(i for i, b in enumerate(bars) if hhmm(b.open_time) == "10:30")
        assert held[short_bar] is None  # stopped out inside the 10:30 bar
        assert held[short_bar - 1] is Direction.LONG
        # the same signals and trades; only the version (it hashes the policy) differs
        assert unversioned(ignore) == unversioned(reverse)
        assert [(e.kind, e.time, e.price, e.reason) for e in ignore.events] == [
            (e.kind, e.time, e.price, e.reason) for e in reverse.events
        ]


def unversioned(result: StrategyTestResult) -> list[dict[str, Any]]:
    return [{k: v for k, v in s.items() if k != "strategy_version"} for s in dumps(result)]

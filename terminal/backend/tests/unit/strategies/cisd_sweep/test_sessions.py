"""S6's sweep levels by New York session and trading period: when a session high/low is a
level (only after its session, DST-correct, every day), the trade-through rule, levels
that are never retired, a pivot cleared by any same-side sweep, and PDH/PWH on the
instrument's trading day (17:00 New York, UTC midnight for crypto).

The tapes are quiet bars around 100 (highs 100.15, lows 99.85, no pivots), so every
session range is 100.15 / 99.85 unless a scripted bar widens it; the strategy's state
after the last bar (``strategy_object``) shows the latest buy-side sweep and the levels
it took.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from kterminal.strategies.cisd_sweep import CisdSweep
from tests.unit.strategies.cisd_sweep.scenario import Row, Tape, ny, run_tape
from tests.unit.strategies.pine_port_support import real_catalog, strategy_object

TUESDAY = date(2026, 1, 6)
HIGH_100_5: Row = (100.0, 100.5, 99.85, 100.1)


def last_state(tape: Tape, **kwargs: Any) -> Any:
    return strategy_object(run_tape(CisdSweep, tape, **kwargs))


def sweep_of(state: Any) -> tuple[datetime | None, list[Any]]:
    return state.bsl.time, state.bsl.levels


@pytest.mark.parametrize("day", [TUESDAY, date(2026, 7, 7)], ids=["winter-EST", "summer-EDT"])
def test_the_asia_range_is_a_level_from_its_end_at_midnight(day: date) -> None:
    monday = day - timedelta(days=1)
    # 21:00 inside Asia (20:00-00:00): the range high becomes 100.5 (and a 5/5 pivot)
    tape = Tape(ny(monday, "18:00")).at(ny(monday, "21:00"), HIGH_100_5)
    tape.at(ny(day, "00:30"), (100.0, 100.7, 99.85, 100.1)).quiet(2)
    state = last_state(tape)
    assert sweep_of(state) == (
        ny(day, "00:30"),
        [{"level": "pivot high", "price": 100.5}, {"level": "Asia high", "price": 100.5}],
    )
    assert state.asia.start == ny(monday, "20:00") and state.asia.bars == 48

    # the same bar inside the session takes the pivot only, and extends the range
    inside = Tape(ny(monday, "18:00")).at(ny(monday, "21:00"), HIGH_100_5)
    inside.at(ny(monday, "23:00"), (100.0, 100.7, 99.85, 100.1)).quiet(2)
    state = last_state(inside)
    assert sweep_of(state) == (ny(monday, "23:00"), [{"level": "pivot high", "price": 100.5}])
    assert state.asia.high == 100.7


def test_a_level_is_taken_only_by_a_trade_through_and_never_retired() -> None:
    monday = TUESDAY - timedelta(days=1)
    rows: list[Row] = [
        (100.0, 100.8, 99.85, 100.1),  # 01:00 takes the Asia high 100.15
        (100.1, 100.9, 99.85, 100.0),  # 01:05 high[1] 100.8 > 100.15: no new sweep
        (100.0, 100.15, 99.85, 100.1),  # 01:10 back below
        (100.1, 100.5, 99.85, 100.0),  # 01:15 takes it again: levels are never retired
    ]
    asia = [{"level": "Asia high", "price": 100.15}]
    for count, expected in ((2, "01:00"), (4, "01:15")):
        tape = Tape(ny(monday, "18:00")).at(ny(TUESDAY, "01:00"), *rows[:count])
        assert sweep_of(last_state(tape)) == (ny(TUESDAY, expected), asia)


def test_any_buy_side_sweep_clears_the_pivot_high() -> None:
    monday = TUESDAY - timedelta(days=1)

    def tape(*later: Row) -> Tape:
        t = Tape(ny(monday, "18:00"))
        t.at(ny(TUESDAY, "01:00"), (100.0, 101.0, 99.85, 100.1))  # pivot high 101.0
        return t.at(ny(TUESDAY, "01:40"), *later)

    breakout: Row = (100.1, 101.2, 99.85, 100.0)
    quiet: Row = (100.0, 100.15, 99.85, 100.1)
    state = last_state(tape(quiet, quiet, breakout))  # 01:50 takes the pivot and Asia
    assert sweep_of(state)[1] == [
        {"level": "pivot high", "price": 101.0},
        {"level": "Asia high", "price": 100.15},
    ]
    # an Asia-high sweep at 01:40 clears lastPH (L621): the 01:50 breakout takes Asia only
    state = last_state(tape((100.1, 100.5, 99.85, 100.0), quiet, breakout))
    assert sweep_of(state) == (ny(TUESDAY, "01:50"), [{"level": "Asia high", "price": 100.15}])


def test_london_starts_at_03_00_on_the_night_the_clocks_go_forward() -> None:
    saturday = date(2026, 3, 7)
    dst_night = date(2026, 3, 8)  # 02:00 EST → 03:00 EDT: 02:00-03:00 does not exist
    tape = Tape(ny(saturday, "18:00")).quiet_until(ny(dst_night, "06:00"))
    state = last_state(tape)
    assert state.london.start == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)  # 03:00 EDT
    assert state.london.bars == 24  # 03:00-05:00
    normal = Tape(ny(dst_night, "18:00")).quiet_until(ny(date(2026, 3, 9), "06:00"))
    state = last_state(normal)
    assert state.london.start == datetime(2026, 3, 9, 6, 0, tzinfo=UTC)  # 02:00 EDT
    assert state.london.bars == 36


def test_before_09_30_the_previous_ny_am_range_is_live() -> None:
    monday = TUESDAY - timedelta(days=1)
    wednesday = TUESDAY + timedelta(days=1)
    tape = Tape(ny(monday, "18:00")).at(ny(TUESDAY, "10:00"), (100.0, 100.6, 99.85, 100.1))
    tape.at(ny(wednesday, "08:00"), (100.0, 100.8, 99.85, 100.1)).quiet(2)
    time, levels = sweep_of(last_state(tape))
    assert time == ny(wednesday, "08:00")
    assert levels == [
        {"level": "pivot high", "price": 100.6},
        {"level": "Asia high", "price": 100.15},
        {"level": "LNDN high", "price": 100.15},
        {"level": "NY AM high", "price": 100.6},  # Tuesday's 09:30-12:00
    ]


def test_crypto_sessions_run_on_saturday_and_days_roll_at_utc_midnight() -> None:
    btc = real_catalog().instrument("BTCUSD")
    friday = date(2026, 1, 9)
    saturday = date(2026, 1, 10)
    tape = Tape(datetime(2026, 1, 9, 0, 0, tzinfo=UTC), symbol="BTCUSD")  # a whole UTC day
    tape.at(datetime(2026, 1, 9, 12, 0, tzinfo=UTC), (100.0, 100.6, 99.85, 100.1))
    tape.at(ny(saturday, "06:00"), (100.0, 100.7, 99.85, 100.1)).quiet(2)
    state = last_state(tape, instrument=btc)
    time, levels = sweep_of(state)
    assert time == ny(saturday, "06:00")
    assert levels == [
        {"level": "pivot high", "price": 100.6},
        {"level": "PDH", "price": 100.6},  # Friday's UTC day
        {"level": "Asia high", "price": 100.15},  # Friday 20:00-00:00 New York
        {"level": "LNDN high", "price": 100.15},  # Saturday 02:00-05:00: no day mask
        {"level": "NY AM high", "price": 100.15},  # Friday's
    ]
    assert state.london.start == ny(saturday, "02:00")
    assert state.asia.start == ny(friday, "20:00")


def test_pdh_and_pwh_follow_the_17_00_new_york_trading_day() -> None:
    sunday = date(2026, 1, 4)
    # Sunday 17:00 New York starts Monday's trading day and the week: both complete
    tape = Tape(ny(sunday, "17:00"))
    tape.at(ny(date(2026, 1, 5), "10:00"), (100.0, 100.6, 99.85, 100.1))  # Monday's high
    tape.at(ny(date(2026, 1, 5), "16:55"), (100.0, 100.4, 99.85, 100.1))  # still Monday
    tape.at(ny(date(2026, 1, 5), "17:05"), (100.0, 100.7, 99.85, 100.1))  # Tuesday: PDH
    state = last_state(tape.quiet(1))
    time, levels = sweep_of(state)
    assert time == ny(date(2026, 1, 5), "17:05")
    assert {"level": "PDH", "price": 100.6} in levels
    # a week later the first bar of the new week takes Monday's high as PWH
    week = Tape(ny(sunday, "17:00"))
    week.at(ny(date(2026, 1, 5), "10:00"), (100.0, 100.6, 99.85, 100.1))
    week.at(ny(date(2026, 1, 11), "17:00"), (100.0, 100.7, 99.85, 100.1)).quiet(1)
    time, levels = sweep_of(last_state(week))
    assert time == ny(date(2026, 1, 11), "17:00")
    assert {"level": "PWH", "price": 100.6} in levels
    assert {"level": "PDH", "price": 100.15} in levels  # Sunday's (quiet) trading day

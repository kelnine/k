"""Model D's key levels on hand-built tapes: the overnight session 18:00-09:30 New York
(its volume-profile value area and high/low, computed on the first bar after it, L835-854)
across the clock changes, and the previous day's high/low on the doc 13 D8 trading day
(``ctx.periods``, L620) — and trades taken at them."""

import math
from datetime import UTC, date, datetime
from typing import Any

import pytest

from kterminal.core.enums import SignalAction
from kterminal.domain.instruments import Instrument
from kterminal.strategies.ict_model_d import IctModelD, value_area
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.ict_model_d.scenario import (
    HOLD,
    SETUP,
    Row,
    Tape,
    ny,
    run_1m,
    with_htf,
    zone_part,
)
from tests.unit.strategies.pine_port_support import real_catalog, strategy_object

DAY = date(2026, 1, 6)  # a Tuesday in winter
LEVELS_ONLY = {"d_zone_mode": "Key levels only"}
NAN_LEVELS = {"VAH", "VAL", "ONH", "ONL", "PDH", "PDL"}


def d(
    tape: Tape, params: dict[str, Any] | None = None, instrument: Instrument = XAUUSD
) -> StrategyTestResult:
    result = run_1m(IctModelD, with_htf(tape.bars()), params=params, instrument=instrument)
    assert result.fault is None and result.rejected == []
    return result


def levels(result: StrategyTestResult) -> dict[str, float]:
    """The key levels the strategy would test on its last bar."""
    return dict(strategy_object(result)._key_levels())


def overnight_tape(day: date, *, until: str = "09:31") -> Tape:
    """The previous evening 17:00 → ``until`` at 110, a spike to 111 at 02:00 and a dip to
    109 at 05:00 (the overnight high and low)."""
    previous = date.fromordinal(day.toordinal() - 1)
    tape = Tape(ny(previous, "17:00"), level=110.0)
    tape.at(ny(day, "02:00"), (110.0, 111.0, 109.9, 110.1, 100.0))
    tape.at(ny(day, "05:00"), (110.1, 110.2, 109.0, 110.0, 100.0))
    return tape.quiet_until(ny(day, until), 110.0)


def test_the_overnight_profile_is_computed_on_the_first_bar_after_the_session() -> None:
    tape = overnight_tape(DAY)
    before = levels(d(tape.cut(ny(DAY, "09:30"))))
    assert all(math.isnan(before[name]) for name in NAN_LEVELS - {"PDH", "PDL"})
    result = d(tape)
    profile = strategy_object(result)._profile
    assert profile.session_bars == 930  # 18:00-09:29, 15.5 hours
    assert (profile.levels_high, profile.levels_low) == (111.0, 109.0)
    # the session's own bars, by open time in [18:00, 09:30)
    rows = tape.rows[tape.index(ny(date(2026, 1, 5), "18:00")) : tape.index(ny(DAY, "09:30"))]
    area = value_area(
        [r[1] for r in rows], [r[2] for r in rows], [r[4] for r in rows], 109.0, 111.0, 50, 70.0
    )
    assert (profile.vah, profile.val, profile.poc) == (area.vah, area.val, area.poc)
    got = levels(result)
    assert (got["VAH"], got["VAL"], got["ONH"], got["ONL"]) == (area.vah, area.val, 111.0, 109.0)
    # the flat 110 tape holds the volume: the value area brackets it
    assert 109.0 < area.val < 110.0 < area.vah < 111.0


def test_the_levels_stay_until_the_next_session_ends() -> None:
    """The next overnight session (from 18:00) restarts the stored bars; the morning's
    levels are kept and replaced at the next 09:30."""
    tape = overnight_tape(DAY, until="20:00")
    overnight = ("VAH", "VAL", "ONH", "ONL")
    morning = levels(d(overnight_tape(DAY)))
    evening_result = d(tape)
    evening = levels(evening_result)
    assert [evening[k] for k in overnight] == [morning[k] for k in overnight]
    # Tuesday's trading day ended at 17:00: its high and low are the previous day now
    assert (evening["PDH"], evening["PDL"]) == (111.0, 109.0)
    assert strategy_object(evening_result)._profile.bars == 120  # 18:00-19:59
    next_day = date(2026, 1, 7)
    tape.quiet_until(ny(next_day, "09:31"), 110.0)
    replaced = levels(d(tape))
    assert (replaced["ONH"], replaced["ONL"]) == (110.15, 109.85)  # a flat night
    assert replaced["VAH"] != morning["VAH"]


@pytest.mark.parametrize(
    ("day", "bars"),
    [(date(2026, 11, 1), 990), (date(2026, 3, 8), 870), (date(2026, 6, 14), 930)],
    ids=["fall-back-17.5h", "spring-forward-14.5h", "summer-15.5h"],
)
def test_the_overnight_session_follows_new_york_across_the_clock_changes(
    day: date, bars: int
) -> None:
    """Crypto trades through the night of the change: 18:00 EDT → 09:30 EST is 16.5 h,
    18:00 EST → 09:30 EDT 14.5 h (in bars, one per minute)."""
    btc = real_catalog().instrument("BTCUSD")
    previous = date.fromordinal(day.toordinal() - 1)
    tape = Tape(ny(previous, "17:00"), symbol="BTCUSD", level=110.0)
    tape.quiet_until(ny(day, "09:31"))
    profile = strategy_object(d(tape, instrument=btc))._profile
    assert profile.session_bars == bars


def test_a_trade_at_the_overnight_high() -> None:
    """The overnight high is support for the sellers (and resistance, L869-871); with
    ``useON`` off the same bars do not trade."""
    tape = overnight_tape(DAY, until="09:30")
    tape.at(ny(DAY, "09:30"), (110.1, 111.15, 110.0, 111.0, 100.0))  # up to 111
    tape.at(ny(DAY, "10:00"), *SETUP, *HOLD).quiet_until(ny(DAY, "10:30"))
    params = {**LEVELS_ONLY, "use_va": False, "use_pd": False}
    # the selling bar 110.4-111.05 is 0.4 above the 111.0 overnight high: it overlaps it
    (signal,) = d(tape, params).signals
    assert signal.signal is SignalAction.LONG
    cand = signal.metadata["candidate"]
    assert isinstance(cand, dict)
    assert cand["at"] == [{"kind": "level", "name": "ONH", "price": 111.0}]
    assert d(tape, {**params, "use_on": False}).signals == []


def previous_day_tape(spike: Row) -> Tape:
    """Monday 17:00 (the start of Tuesday's trading day) → Wednesday: Tuesday at 110 with
    ``spike`` at 03:00, then Wednesday's zone and setup from 09:30."""
    wednesday = date(2026, 1, 7)
    tape = Tape(ny(date(2026, 1, 5), "17:00"), level=110.0)
    tape.at(ny(DAY, "03:00"), spike).quiet_until(ny(wednesday, "09:30"), 110.0)
    zone_part(tape, wednesday)
    tape.at(ny(wednesday, "11:00"), *SETUP, *HOLD)
    return tape.quiet_until(ny(wednesday, "12:00"))


def test_previous_day_high_and_low_follow_the_17_00_trading_day() -> None:
    """D8: XAUUSD's trading day starts at 17:00 New York. Tuesday's day (Monday 17:00 →
    Tuesday 17:00) is the previous day from Tuesday 17:00 on, not before."""
    tape = previous_day_tape((110.0, 110.6, 109.5, 110.1, 100.0))
    at_1659 = levels(d(tape.cut(ny(DAY, "17:00"))))
    assert math.isnan(at_1659["PDH"]) and math.isnan(at_1659["PDL"])
    at_1700 = levels(d(tape.cut(ny(DAY, "17:01"))))
    assert (at_1700["PDH"], at_1700["PDL"]) == (110.6, 109.5)
    params = {**LEVELS_ONLY, "use_va": False, "use_on": False}
    (signal,) = d(tape, params).signals  # Wednesday's sellers overlap the 110.6 PDH
    assert signal.signal is SignalAction.LONG
    cand = signal.metadata["candidate"]
    assert isinstance(cand, dict)
    assert cand["at"] == [{"kind": "level", "name": "PDH", "price": 110.6}]
    assert d(tape, {**params, "use_pd": False}).signals == []


def test_crypto_previous_day_starts_at_midnight_utc() -> None:
    """D8: crypto's trading day is the UTC calendar day."""
    btc = real_catalog().instrument("BTCUSD")
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    tape = Tape(start, symbol="BTCUSD", level=110.0)
    tape.at(datetime(2026, 1, 5, 12, 0, tzinfo=UTC), (110.0, 112.0, 108.0, 110.0, 100.0))
    tape.quiet_until(datetime(2026, 1, 5, 23, 59, tzinfo=UTC), 110.0)
    assert math.isnan(levels(d(tape, instrument=btc))["PDH"])
    tape.quiet_until(datetime(2026, 1, 6, 0, 1, tzinfo=UTC))
    got = levels(d(tape, instrument=btc))
    assert (got["PDH"], got["PDL"]) == (112.0, 108.0)

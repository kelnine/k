"""Pine session strings: bar-open membership, DST, midnight, day masks, window starts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from kterminal.core.registry import Registry
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import H1
from kterminal.strategy_engine import (
    CloseReason,
    PositionEventKind,
    SessionString,
    StrategyParams,
    TimeZoneName,
    in_session,
    parse_session,
    session_started,
)
from kterminal.strategy_engine.instances import InstanceSpec, resolve_instance
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from kterminal.strategy_engine.testing import run_strategy
from tests.fixtures.engine_strategies import WindowFlat
from tests.fixtures.instruments import INSTRUMENTS, XAUUSD

NY = "America/New_York"
NEW_YORK = ZoneInfo(NY)


def ny(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    """A New York wall-clock time as a UTC instant."""
    return datetime(y, m, d, h, mi, tzinfo=NEW_YORK).astimezone(UTC)


def inside(session: str, *times: datetime, tz: str = NY) -> list[bool]:
    return [in_session(t, session, tz) for t in times]


def test_regular_hours_follow_new_york_daylight_saving_time() -> None:
    # winter (EST, UTC-5)
    assert inside("0930-1600", ny(2026, 1, 5, 9, 25), ny(2026, 1, 5, 9, 30)) == [False, True]
    assert ny(2026, 1, 5, 9, 30) == datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    assert inside("0930-1600", ny(2026, 1, 5, 15, 55), ny(2026, 1, 5, 16, 0)) == [True, False]
    # summer (EDT, UTC-4): the same local window is an hour earlier in UTC
    summer_open = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    assert inside("0930-1600", summer_open, summer_open - timedelta(minutes=5)) == [True, False]
    assert inside("0930-1600", datetime(2026, 7, 6, 20, 0, tzinfo=UTC)) == [False]
    # the Friday before and the Monday after the spring-forward weekend (2026-03-08)
    assert inside("0930-1600", datetime(2026, 3, 6, 14, 30, tzinfo=UTC)) == [True]
    assert inside("0930-1600", datetime(2026, 3, 6, 13, 30, tzinfo=UTC)) == [False]
    assert inside("0930-1600", datetime(2026, 3, 9, 13, 30, tzinfo=UTC)) == [True]


def test_membership_is_by_bar_open_time_and_half_open() -> None:
    opens = [ny(2026, 1, 5, 9, m) for m in (25, 30, 35, 40, 45)]  # 5m bars
    assert inside("0930-0945", *opens) == [False, True, True, True, False]


def test_a_window_crossing_midnight() -> None:
    assert inside(
        "2000-0200",
        ny(2026, 1, 5, 19, 59),
        ny(2026, 1, 5, 20, 0),
        ny(2026, 1, 5, 23, 59),
        ny(2026, 1, 6, 0, 0),
        ny(2026, 1, 6, 1, 59),
        ny(2026, 1, 6, 2, 0),
    ) == [False, True, True, True, True, False]


def test_midnight_windows_on_daylight_saving_nights() -> None:
    spec = parse_session("2000-0200", NY)
    # spring forward (Sun 2026-03-08 02:00 EST → 03:00 EDT): 02:00 does not exist and
    # moves forward by the gap, so the Saturday-night window ends at 03:00 EDT (07:00 UTC)
    assert spec.window_at(datetime(2026, 3, 8, 6, 59, tzinfo=UTC)) == (
        datetime(2026, 3, 8, 1, 0, tzinfo=UTC),
        datetime(2026, 3, 8, 7, 0, tzinfo=UTC),
    )
    assert not spec.contains(datetime(2026, 3, 8, 7, 0, tzinfo=UTC))
    # the Sunday-night window is already on EDT: 00:00-06:00 UTC
    assert spec.contains(datetime(2026, 3, 9, 0, 0, tzinfo=UTC))
    assert not spec.contains(datetime(2026, 3, 9, 6, 0, tzinfo=UTC))
    # fall back (Sun 2026-11-01 02:00 EDT → 01:00 EST): the window holds the repeated hour
    window = spec.window_at(datetime(2026, 11, 1, 6, 30, tzinfo=UTC))  # 01:30 EST
    assert window == (
        datetime(2026, 11, 1, 0, 0, tzinfo=UTC),
        datetime(2026, 11, 1, 7, 0, tzinfo=UTC),
    )
    assert spec.contains(datetime(2026, 11, 1, 5, 30, tzinfo=UTC))  # 01:30 EDT
    assert not spec.contains(datetime(2026, 11, 1, 7, 0, tzinfo=UTC))  # 02:00 EST


def test_london_windows_use_london_time() -> None:
    # 08:00 London is 08:00 UTC in winter and 07:00 UTC in summer (BST from 2026-03-29)
    assert in_session(datetime(2026, 3, 27, 8, 0, tzinfo=UTC), "0800-0900", "Europe/London")
    assert not in_session(datetime(2026, 3, 30, 8, 0, tzinfo=UTC), "0800-0900", "Europe/London")
    assert in_session(datetime(2026, 3, 30, 7, 0, tzinfo=UTC), "0800-0900", "Europe/London")


def test_day_masks_use_pine_numbering_sunday_is_one() -> None:
    saturday, sunday, monday = (ny(2026, 1, d, 10) for d in (10, 11, 12))
    assert inside("0930-1600:23456", saturday, sunday, monday) == [False, False, True]
    assert inside("0930-1600:17", saturday, sunday, monday) == [True, True, False]
    assert inside("0930-1600", saturday, sunday, monday) == [True, True, True]  # default: all
    assert in_session(monday, "0930-1600", NY, days=":2")
    assert not in_session(sunday, "0930-1600", NY, days="23456")


def test_an_overnight_range_belongs_to_the_day_it_ends_on() -> None:
    # "1700-1700:23456" is the FX week: Sunday 17:00 → Friday 17:00 New York
    fx = "1700-1700:23456"
    assert inside(fx, ny(2026, 1, 4, 16, 59), ny(2026, 1, 4, 17, 0)) == [False, True]
    assert inside(fx, ny(2026, 1, 9, 16, 59), ny(2026, 1, 9, 17, 0)) == [True, False]
    assert inside(fx, ny(2026, 1, 10, 12, 0)) == [False]
    # "2000-0200:23456": Sunday night belongs to Monday, Friday night to Saturday
    nights = "2000-0200:23456"
    assert inside(nights, ny(2026, 1, 4, 20, 0), ny(2026, 1, 5, 1, 30)) == [True, True]
    assert inside(nights, ny(2026, 1, 8, 20, 0), ny(2026, 1, 9, 1, 30)) == [True, True]
    assert inside(nights, ny(2026, 1, 9, 20, 0), ny(2026, 1, 10, 1, 30)) == [False, False]


def test_an_end_of_0000_is_midnight_at_the_end_of_the_start_day() -> None:
    asia = "2000-0000:2"  # Monday 20:00 → 24:00
    assert inside(
        asia,
        ny(2026, 1, 4, 20, 0),
        ny(2026, 1, 5, 20, 0),
        ny(2026, 1, 5, 23, 59),
        ny(2026, 1, 6, 0, 0),
    ) == [False, True, True, False]
    assert parse_session("0000-0000", NY).text == parse_session("24x7", NY).text
    assert parse_session("24x7", NY).text == "0000-0000:1234567"
    assert all(inside("24x7", ny(2026, 1, d, h)) == [True] for d in (3, 4, 5) for h in (0, 12, 23))


def test_several_ranges_and_shared_masks() -> None:
    split = "0900-1200,1330-1600:23456"
    assert parse_session(split, NY).text == "0900-1200,1330-1600:23456"
    times = (ny(2026, 1, 5, 11, 59), ny(2026, 1, 5, 12, 0), ny(2026, 1, 5, 13, 30))
    assert inside(split, *times) == [True, False, True]
    assert inside(split, ny(2026, 1, 10, 13, 30)) == [False]  # the mask covers both ranges
    mixed = parse_session("0900-1000:1,1100-1200:2", NY)
    assert mixed.text == "0900-1000:1,1100-1200:2"
    assert mixed.contains(ny(2026, 1, 4, 9, 0)) and not mixed.contains(ny(2026, 1, 5, 9, 0))
    assert mixed.contains(ny(2026, 1, 5, 11, 0))
    assert parse_session(" 2000 - 0200 ", NY).text == "2000-0200:1234567"


def test_window_started_is_pines_in_session_and_not_previous() -> None:
    opens = [ny(2026, 1, 5, 19, 50) + timedelta(minutes=5 * i) for i in range(5)]
    starts = [
        session_started(t, prev, "2000-0200", NY)
        for t, prev in zip(opens, [None, *opens[:-1]], strict=True)
    ]
    assert starts == [False, False, True, False, False]
    assert session_started(opens[3], None, "2000-0200", NY)  # first bar of the data, inside
    # A gap across the closed hours: the previous bar was inside yesterday's window, so
    # (as in the script) this is not a start, although the occurrence is a new one.
    spec = parse_session("2000-0200", NY)
    yesterday, today = ny(2026, 1, 5, 1, 55), ny(2026, 1, 5, 20, 0)
    assert not spec.started(today, yesterday)
    assert spec.window_at(today) != spec.window_at(yesterday)


def test_last_bar_of_a_window() -> None:
    spec = parse_session("0930-1600", NY)
    five = timedelta(minutes=5)
    assert spec.ends_by(ny(2026, 1, 5, 15, 55), ny(2026, 1, 5, 15, 55) + five)
    assert not spec.ends_by(ny(2026, 1, 5, 15, 50), ny(2026, 1, 5, 15, 50) + five)
    assert not spec.ends_by(ny(2026, 1, 5, 16, 0), ny(2026, 1, 5, 16, 0) + five)  # outside
    one = timedelta(minutes=1)
    assert spec.ends_by(ny(2026, 1, 5, 15, 59), ny(2026, 1, 5, 15, 59) + one)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "0930",
        "2500-0100",
        "0960-1000",
        "0930-1600:8",
        "0930-1600:",
        "0930-1600:0",
        "9:30-16:00",
        "0930-1600;23456",
        "0930-1600,",
    ],
)
def test_malformed_sessions_are_refused(text: str) -> None:
    with pytest.raises(ValueError, match="session"):
        parse_session(text, NY)


def test_bad_zones_and_day_arguments_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown IANA time zone"):
        parse_session("0930-1600", "Mars/Olympus")
    with pytest.raises(ValueError, match="not an IANA time zone"):
        parse_session("0930-1600", "localtime")
    with pytest.raises(ValueError, match="its own days mask"):
        parse_session("0930-1600:23456", NY, days="23456")
    with pytest.raises(ValueError, match="digits 1-7"):
        parse_session("0930-1600", NY, days="weekdays")


class SessionParams(StrategyParams):
    window: SessionString = "2000-0200"
    tz: TimeZoneName = NY


def test_session_parameters_are_validated_and_normalised() -> None:
    assert SessionParams().window == "2000-0200:1234567"  # defaults are normalised too
    assert SessionParams(window="2000-0200:1234567") == SessionParams()
    assert SessionParams(window="0930-1600:23456").window == "0930-1600:23456"
    with pytest.raises(ValidationError, match="session"):
        SessionParams(window="20:00-02:00")
    with pytest.raises(ValidationError, match="time zone"):
        SessionParams(tz="New York")


def test_session_parameters_are_part_of_the_version() -> None:
    registry: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(WindowFlat)
    registry.register(definition.id, definition)

    def version(**params: str) -> str:
        spec = InstanceSpec(
            id="window_a",
            strategy="window_flat",
            params=params,
            instruments=("XAUUSD",),
            timeframe="1h",
        )
        return resolve_instance(spec, instruments=INSTRUMENTS, definitions=registry).version

    assert version() == version(window="2000-0200:1234567") == version(window="2000-0200")
    assert version() != version(window="2000-0100")
    assert version() != version(timezone="Europe/London")


def test_a_strategy_enters_at_the_window_start_and_closes_at_its_end() -> None:
    start = ny(2026, 1, 5, 18)  # hourly bars 18:00 … next day 04:00 New York
    hourly = [
        Bar.of("XAUUSD", H1, start + i * H1.duration, 4000, 4001, 3999, 4000) for i in range(11)
    ]
    result = run_strategy(WindowFlat, instrument=XAUUSD, bars=hourly, timeframe="1h")
    assert result.fault is None
    long, exit_ = result.signals
    assert long.bar_time == ny(2026, 1, 5, 20)  # the first bar inside 20:00-02:00
    assert exit_.bar_time == ny(2026, 1, 6, 1) and exit_.reason == "SESSION_CLOSE"  # the last
    opened, closed = result.events
    assert opened.kind is PositionEventKind.OPENED and opened.time == ny(2026, 1, 5, 21)
    assert closed.reason is CloseReason.SESSION_CLOSE and closed.time == ny(2026, 1, 6, 2)
    assert closed.price == Decimal("4000.00")

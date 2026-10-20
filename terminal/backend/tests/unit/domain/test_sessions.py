"""Trading calendars, trading-day rules, session windows and DST.

Reference dates (2026): US DST starts 2026-03-08 and ends 2026-11-01; UK BST
starts 2026-03-29 and ends 2026-10-25. Between those pairs of dates London
and New York are only four hours apart instead of five.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from kterminal.core.errors import ClockError
from kterminal.domain.sessions import (
    OFF_HOURS,
    UNBOUNDED_END,
    UNBOUNDED_START,
    HolidayRule,
    SessionBook,
    SessionWindow,
    TradingCalendar,
    TradingDayRule,
    Weekday,
    WeeklyInterval,
    parse_date,
    parse_time,
    parse_weekdays,
    to_local,
    to_utc,
    week_order,
    zone,
)

SESSIONS_YAML = Path(__file__).resolve().parents[4] / "config" / "catalog" / "sessions.yaml"

NY = "America/New_York"
CHI = "America/Chicago"
LON = "Europe/London"
MON_FRI = frozenset({Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI})
EVERY_DAY = frozenset(Weekday)


def utc(y: int, m: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, s, tzinfo=UTC)


def local(tz: str, y: int, m: int, d: int, h: int = 0, mi: int = 0, s: int = 0) -> datetime:
    """An aware local time (only used for unambiguous wall-clock times)."""
    return datetime(y, m, d, h, mi, s, tzinfo=ZoneInfo(tz))


def wall(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    """A naive local wall-clock time, the input of ``to_utc``."""
    return datetime.combine(date(y, m, d), time(h, mi))


def hhmm(ts: datetime, tz: str) -> str:
    return to_local(ts, tz).strftime("%H:%M")


@pytest.fixture(scope="module")
def raw_doc() -> dict[str, Any]:
    with SESSIONS_YAML.open(encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    assert isinstance(doc, dict)
    return doc


@pytest.fixture(scope="module")
def book(raw_doc: dict[str, Any]) -> SessionBook:
    return SessionBook.from_document(raw_doc)


def _book() -> SessionBook:
    """The configured book, for hypothesis tests (which cannot take function fixtures)."""
    with SESSIONS_YAML.open(encoding="utf-8") as handle:
        return SessionBook.from_document(yaml.safe_load(handle))


BOOK = _book()


def weekly(*texts: str) -> tuple[WeeklyInterval, ...]:
    return tuple(WeeklyInterval.parse(text) for text in texts)


# ════════════════════════════════════════════════════════════════════════════
# Weekdays
# ════════════════════════════════════════════════════════════════════════════
def test_weekday_numbering_matches_date_weekday() -> None:
    assert Weekday.parse("MON") is Weekday.MON
    assert Weekday.parse("sun") is Weekday.SUN
    assert Weekday.parse(" Friday ") is Weekday.FRI
    assert Weekday.parse(3) is Weekday.THU
    assert Weekday.of(date(2026, 10, 6)) is Weekday.TUE
    for day in range(7):
        sample = date(2026, 10, 5) + timedelta(days=day)
        assert Weekday.of(sample) == sample.weekday()
    assert str(Weekday.SAT) == "SAT"


@pytest.mark.parametrize("raw", ["MO", "Funday", 7, -1, "", True])
def test_weekday_parse_rejects_garbage(raw: Any) -> None:
    with pytest.raises(ValueError, match="weekday"):
        Weekday.parse(raw)


def test_parse_weekdays_lists_and_ranges() -> None:
    assert parse_weekdays(["MON", "WED"]) == {Weekday.MON, Weekday.WED}
    assert parse_weekdays("MON-FRI") == MON_FRI
    assert parse_weekdays("SUN-THU") == {
        Weekday.SUN,
        Weekday.MON,
        Weekday.TUE,
        Weekday.WED,
        Weekday.THU,
    }
    assert parse_weekdays("SAT,SUN") == {Weekday.SAT, Weekday.SUN}
    with pytest.raises(ValueError, match="weekdays"):
        parse_weekdays(5)


def test_week_order_reads_naturally() -> None:
    assert week_order(parse_weekdays("SUN-THU")) == [
        Weekday.SUN,
        Weekday.MON,
        Weekday.TUE,
        Weekday.WED,
        Weekday.THU,
    ]
    assert week_order(MON_FRI) == sorted(MON_FRI)
    assert week_order({Weekday.WED, Weekday.MON}) == [Weekday.MON, Weekday.WED]
    assert week_order(EVERY_DAY) == sorted(EVERY_DAY)


# ════════════════════════════════════════════════════════════════════════════
# to_utc: DST gaps and ambiguity
# ════════════════════════════════════════════════════════════════════════════
def test_to_utc_regular_winter_and_summer() -> None:
    assert to_utc(wall(2026, 1, 14, 9, 30), NY) == utc(2026, 1, 14, 14, 30)  # EST, UTC-5
    assert to_utc(wall(2026, 7, 15, 9, 30), NY) == utc(2026, 7, 15, 13, 30)  # EDT, UTC-4
    assert to_utc(wall(2026, 7, 15, 9, 30), "UTC") == utc(2026, 7, 15, 9, 30)
    assert to_utc(wall(2026, 7, 15, 9, 30), ZoneInfo("Asia/Tokyo")) == utc(2026, 7, 15, 0, 30)


def test_nonexistent_time_shifts_forward_by_the_gap() -> None:
    """02:00-03:00 does not exist in New York on 2026-03-08 (clocks jump 02:00 EST → 03:00 EDT)."""
    shifted = to_utc(wall(2026, 3, 8, 2, 30), NY)
    assert shifted == utc(2026, 3, 8, 7, 30)
    assert to_local(shifted, NY).replace(tzinfo=None) == wall(2026, 3, 8, 3, 30)  # +1 h gap
    assert to_utc(wall(2026, 3, 8, 2, 0), NY) == to_utc(wall(2026, 3, 8, 3, 0), NY)
    # Around the gap nothing moves.
    assert to_utc(wall(2026, 3, 8, 1, 59), NY) == utc(2026, 3, 8, 6, 59)
    assert to_utc(wall(2026, 3, 8, 3, 0), NY) == utc(2026, 3, 8, 7, 0)
    # London's gap (01:00-02:00 on 2026-03-29) behaves the same way.
    assert to_utc(wall(2026, 3, 29, 1, 30), LON) == utc(2026, 3, 29, 1, 30)
    assert hhmm(to_utc(wall(2026, 3, 29, 1, 30), LON), LON) == "02:30"


def test_ambiguous_time_resolves_to_first_occurrence() -> None:
    """01:00-02:00 happens twice in New York on 2026-11-01 (EDT, then EST)."""
    first, second = utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 6, 30)
    assert hhmm(first, NY) == hhmm(second, NY) == "01:30"  # genuinely ambiguous
    assert to_utc(wall(2026, 11, 1, 1, 30), NY) == first
    assert to_utc(wall(2026, 11, 1, 1, 30).replace(fold=1), NY) == first  # fold is ignored
    assert to_utc(wall(2026, 11, 1, 2, 0), NY) == utc(2026, 11, 1, 7, 0)  # EST after the repeat
    # London repeats 01:00-02:00 on 2026-10-25: first occurrence is BST.
    assert to_utc(wall(2026, 10, 25, 1, 30), LON) == utc(2026, 10, 25, 0, 30)


def test_to_utc_rejects_aware_input_and_unknown_zones() -> None:
    with pytest.raises(ValueError, match="naive"):
        to_utc(utc(2026, 1, 1), NY)
    with pytest.raises(ValueError, match="unknown IANA time zone"):
        to_utc(wall(2026, 1, 1), "America/Gotham")
    with pytest.raises(ValueError, match="unknown IANA time zone"):
        zone("../etc/passwd")
    with pytest.raises(ValueError, match="non-empty"):
        zone("")


# ════════════════════════════════════════════════════════════════════════════
# Document value parsing
# ════════════════════════════════════════════════════════════════════════════
def test_parse_time_and_date() -> None:
    assert parse_time("09:30") == time(9, 30)
    assert parse_time("7:05") == time(7, 5)
    assert parse_time("16:30:15") == time(16, 30, 15)
    assert parse_time(time(8)) == time(8)
    assert parse_date("2026-12-25") == date(2026, 12, 25)
    assert parse_date(date(2026, 12, 25)) == date(2026, 12, 25)


def test_unquoted_yaml_time_is_rejected_with_a_hint() -> None:
    value = yaml.safe_load("rollover: 17:00")["rollover"]
    assert value == 1020  # YAML 1.1 base-60 number
    with pytest.raises(ValueError, match="quoted"):
        parse_time(value)


@pytest.mark.parametrize("raw", ["24:00", "9", "09:60", "noon", None, 9.5])
def test_parse_time_rejects_garbage(raw: Any) -> None:
    with pytest.raises(ValueError, match="time"):
        parse_time(raw)


@pytest.mark.parametrize("raw", ["2026-13-01", "25/12/2026", 20261225, utc(2026, 12, 25)])
def test_parse_date_rejects_garbage(raw: Any) -> None:
    with pytest.raises(ValueError, match="date"):
        parse_date(raw)


# ════════════════════════════════════════════════════════════════════════════
# Weekly intervals
# ════════════════════════════════════════════════════════════════════════════
def test_weekly_interval_parse_and_str_round_trip() -> None:
    interval = WeeklyInterval.parse("SUN 17:00 - MON 16:00")
    assert interval == WeeklyInterval(Weekday.SUN, time(17), Weekday.MON, time(16))
    assert str(interval) == "SUN 17:00 - MON 16:00"
    assert WeeklyInterval.parse(str(interval)) == interval
    assert WeeklyInterval.parse("sun 17:00 → mon 16:00") == interval
    assert interval.duration == timedelta(hours=23)


@pytest.mark.parametrize(
    ("text", "hours"),
    [
        ("MON 09:30 - MON 16:00", 6.5),
        ("SUN 17:00 - FRI 17:00", 120),
        ("FRI 22:00 - MON 01:00", 51),  # wraps over the week end
        ("MON 10:00 - MON 09:00", 7 * 24 - 1),  # close before open on the same day wraps
    ],
)
def test_weekly_interval_durations(text: str, hours: float) -> None:
    assert WeeklyInterval.parse(text).duration == timedelta(hours=hours)


@pytest.mark.parametrize("text", ["SUN 17:00", "SUN 17:00 - XYZ 16:00", "17:00 - 16:00", ""])
def test_weekly_interval_parse_errors(text: str) -> None:
    with pytest.raises(ValueError, match=r"weekly interval|weekday"):
        WeeklyInterval.parse(text)


def test_weekly_interval_without_length_is_rejected() -> None:
    with pytest.raises(ValueError, match="always_open"):
        WeeklyInterval.parse("MON 09:00 - MON 09:00")


# ════════════════════════════════════════════════════════════════════════════
# Trading-day rules
# ════════════════════════════════════════════════════════════════════════════
def test_ny_1700_trading_day(book: SessionBook) -> None:
    rule = book.trading_day_rule("ny_1700")
    assert rule.trading_day(local(NY, 2026, 10, 4, 18)) == date(2026, 10, 5)  # Sun 18:00 → Mon
    assert rule.trading_day(local(NY, 2026, 10, 5, 16, 59, 59)) == date(2026, 10, 5)
    assert rule.trading_day(local(NY, 2026, 10, 5, 17)) == date(2026, 10, 6)
    assert rule.trading_day(local(NY, 2026, 10, 9, 16, 59)) == date(2026, 10, 9)  # Fri 16:59
    assert rule.trading_day(local(NY, 2026, 10, 9, 17)) == date(2026, 10, 10)  # Fri 17:00 → Sat
    # Same rule in winter, where 17:00 New York is 22:00 UTC instead of 21:00.
    assert rule.trading_day(utc(2026, 1, 14, 21, 30)) == date(2026, 1, 14)
    assert rule.trading_day(utc(2026, 7, 15, 21, 30)) == date(2026, 7, 16)


def test_crypto_trading_day_is_the_utc_date(book: SessionBook) -> None:
    rule = book.trading_day_rule("utc_midnight")
    assert rule.trading_day(utc(2026, 10, 5, 23, 59, 59)) == date(2026, 10, 5)
    assert rule.trading_day(utc(2026, 10, 6)) == date(2026, 10, 6)
    assert rule.trading_day(local(NY, 2026, 10, 5, 20)) == date(2026, 10, 6)  # 00:00 UTC
    assert rule.day_bounds(date(2026, 3, 8)) == (utc(2026, 3, 8), utc(2026, 3, 9))


def test_day_bounds_are_23_or_25_hours_across_dst(book: SessionBook) -> None:
    rule = book.trading_day_rule("ny_1700")
    # Trading day 2026-03-08 runs Sat 17:00 EST → Sun 17:00 EDT: 23 hours.
    assert rule.day_bounds(date(2026, 3, 8)) == (utc(2026, 3, 7, 22), utc(2026, 3, 8, 21))
    # Trading day 2026-11-01 runs Sat 17:00 EDT → Sun 17:00 EST: 25 hours.
    assert rule.day_bounds(date(2026, 11, 1)) == (utc(2026, 10, 31, 21), utc(2026, 11, 1, 22))
    assert rule.day_bounds(date(2026, 3, 9)) == (utc(2026, 3, 8, 21), utc(2026, 3, 9, 21))
    midnight = TradingDayRule(id="ny_midnight", timezone=NY, rollover=time(0))
    start, end = midnight.day_bounds(date(2026, 3, 8))
    assert end - start == timedelta(hours=23)
    start, end = midnight.day_bounds(date(2026, 11, 1))
    assert end - start == timedelta(hours=25)


def test_rollover_inside_the_fall_back_hour_is_a_strict_partition() -> None:
    rule = TradingDayRule(id="odd_rollover", timezone=NY, rollover=time(1, 30))
    boundary = rule.day_bounds(date(2026, 11, 1))[1]
    assert boundary == utc(2026, 11, 1, 5, 30)  # the first 01:30 (EDT)
    assert rule.trading_day(utc(2026, 11, 1, 5, 15)) == date(2026, 11, 1)  # first 01:15
    assert rule.trading_day(utc(2026, 11, 1, 5, 30)) == date(2026, 11, 2)  # first 01:30
    # The second 01:15 reads earlier on the wall clock but is later in time.
    assert hhmm(utc(2026, 11, 1, 6, 15), NY) == "01:15"
    assert rule.trading_day(utc(2026, 11, 1, 6, 15)) == date(2026, 11, 2)


def test_rollover_inside_the_spring_gap_shifts_forward() -> None:
    rule = TradingDayRule(id="gap_rollover", timezone=NY, rollover=time(2, 30))
    assert rule.day_bounds(date(2026, 3, 9))[0] == utc(2026, 3, 8, 7, 30)  # 03:30 EDT
    assert rule.trading_day(utc(2026, 3, 8, 7)) == date(2026, 3, 8)  # 03:00 EDT, before it
    assert rule.trading_day(utc(2026, 3, 8, 7, 30)) == date(2026, 3, 9)


def test_trading_day_rule_validation_and_serialization() -> None:
    with pytest.raises(ValueError, match="unknown IANA"):
        TradingDayRule(id="bad_zone", timezone="Mars/Olympus", rollover=time(17))
    with pytest.raises(ValueError, match="invalid trading-day rule id"):
        TradingDayRule(id="NY 1700", timezone=NY, rollover=time(17))
    with pytest.raises(ClockError, match="naive"):
        TradingDayRule(id="ny_1700", timezone=NY, rollover=time(17)).trading_day(wall(2026, 1, 1))
    rule = TradingDayRule.from_dict({"id": "ny_1700", "timezone": NY, "rollover": "17:00"})
    assert rule.to_dict() == {
        "id": "ny_1700",
        "timezone": NY,
        "rollover": "17:00",
        "description": "",
    }
    assert TradingDayRule.from_dict(rule.to_dict()) == rule
    with pytest.raises(ValueError, match="missing required key"):
        TradingDayRule.from_dict({"id": "x_rule", "timezone": NY})


# ════════════════════════════════════════════════════════════════════════════
# Session windows
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    ("day", "utc_open", "ny_open", "regime"),
    [
        (date(2026, 1, 14), "08:00", "03:00", "both on standard time"),
        (date(2026, 3, 9), "08:00", "04:00", "US on DST since 03-08, UK not yet"),
        (date(2026, 3, 18), "08:00", "04:00", "US on DST since 03-08, UK not yet"),
        (date(2026, 3, 27), "08:00", "04:00", "last weekday before the UK switch"),
        (date(2026, 3, 30), "07:00", "03:00", "both on summer time"),
        (date(2026, 7, 15), "07:00", "03:00", "both on summer time"),
        (date(2026, 10, 23), "07:00", "03:00", "last weekday before the UK switch back"),
        (date(2026, 10, 26), "08:00", "04:00", "UK back on GMT since 10-25, US still EDT"),
        (date(2026, 10, 30), "08:00", "04:00", "UK back on GMT since 10-25, US still EDT"),
        (date(2026, 11, 2), "08:00", "03:00", "both on standard time again"),
    ],
)
def test_london_open_in_utc_and_new_york(
    book: SessionBook, day: date, utc_open: str, ny_open: str, regime: str
) -> None:
    window = book.window("london_open").window_on(day)
    assert window is not None, regime
    start, end = window
    assert hhmm(start, LON) == "08:00"
    assert hhmm(end, LON) == "09:00"
    assert hhmm(start, "UTC") == utc_open, regime
    assert hhmm(start, NY) == ny_open, regime
    assert end - start == timedelta(hours=1)


@pytest.mark.parametrize(
    ("day", "start", "end"),
    [
        (date(2026, 1, 14), utc(2026, 1, 14, 14, 30), utc(2026, 1, 14, 14, 45)),  # EST
        (date(2026, 3, 6), utc(2026, 3, 6, 14, 30), utc(2026, 3, 6, 14, 45)),  # Fri before
        (date(2026, 3, 9), utc(2026, 3, 9, 13, 30), utc(2026, 3, 9, 13, 45)),  # Mon after
        (date(2026, 7, 15), utc(2026, 7, 15, 13, 30), utc(2026, 7, 15, 13, 45)),  # EDT
        (date(2026, 11, 2), utc(2026, 11, 2, 14, 30), utc(2026, 11, 2, 14, 45)),  # EST again
    ],
)
def test_ny_orb_15_in_utc_winter_vs_summer(
    book: SessionBook, day: date, start: datetime, end: datetime
) -> None:
    orb = book.window("ny_orb_15")
    assert orb.window_on(day) == (start, end)
    assert orb.contains(start)
    assert orb.contains(end - timedelta(microseconds=1))
    assert not orb.contains(end)  # half-open
    assert not orb.contains(start - timedelta(seconds=1))


def test_orb_windows_have_their_configured_lengths(book: SessionBook) -> None:
    day = date(2026, 10, 6)
    for window_id, minutes in [
        ("ny_orb_5", 5),
        ("ny_orb_15", 15),
        ("ny_orb_30", 30),
        ("london_orb_15", 15),
        ("london_orb_30", 30),
    ]:
        window = book.window(window_id).window_on(day)
        assert window is not None
        assert window[1] - window[0] == timedelta(minutes=minutes), window_id
    london_orb = book.window("london_orb_15").window_on(day)
    assert london_orb is not None
    assert london_orb[0] == utc(2026, 10, 6, 7)  # 08:00 BST


def test_windows_do_not_run_on_unlisted_days(book: SessionBook) -> None:
    saturday, sunday = date(2026, 10, 10), date(2026, 10, 11)
    assert book.window("ny_orb_15").window_on(saturday) is None
    assert book.window("ny_orb_15").window_on(sunday) is None
    assert not book.window("new_york").contains(local(NY, 2026, 10, 10, 10))
    assert book.window("asia_session").window_on(sunday) is not None  # SUN-THU


def test_crossing_midnight_window_and_window_at_after_midnight(book: SessionBook) -> None:
    asia = book.window("asia_session")  # 18:00-03:00 New York, starting SUN-THU
    assert asia.crosses_midnight
    sunday_window = (local(NY, 2026, 10, 4, 18), local(NY, 2026, 10, 5, 3))
    assert asia.window_on(date(2026, 10, 4)) == sunday_window
    # Just after midnight the window that started the previous evening applies.
    assert asia.window_at(local(NY, 2026, 10, 5, 0, 0)) == sunday_window
    assert asia.window_at(local(NY, 2026, 10, 5, 0, 1)) == sunday_window
    assert asia.window_at(local(NY, 2026, 10, 5, 2, 59)) == sunday_window
    assert asia.window_at(local(NY, 2026, 10, 5, 3)) is None
    # Thursday evening's window runs into Friday; Friday evening has none.
    assert asia.contains(local(NY, 2026, 10, 9, 1))
    assert not asia.contains(local(NY, 2026, 10, 9, 19))
    assert not asia.contains(local(NY, 2026, 10, 10, 1))
    # A window ending exactly at midnight excludes midnight itself.
    kill_zone = book.window("asia_kz")
    assert kill_zone.contains(local(NY, 2026, 10, 4, 23, 59))
    assert not kill_zone.contains(local(NY, 2026, 10, 5, 0, 0))


def test_overnight_window_spanning_dst_changes_has_real_length_5_or_7_hours() -> None:
    overnight = SessionWindow(
        id="overnight",
        name="Overnight",
        timezone=NY,
        start=time(22),
        end=time(4),
        days=EVERY_DAY,
    )
    spring = overnight.window_on(date(2026, 3, 7))
    autumn = overnight.window_on(date(2026, 10, 31))
    normal = overnight.window_on(date(2026, 10, 5))
    assert spring is not None
    assert autumn is not None
    assert normal is not None
    assert spring == (utc(2026, 3, 8, 3), utc(2026, 3, 8, 8))
    assert spring[1] - spring[0] == timedelta(hours=5)
    assert autumn[1] - autumn[0] == timedelta(hours=7)
    assert normal[1] - normal[0] == timedelta(hours=6)
    assert overnight.window_at(utc(2026, 3, 8, 7, 30)) == spring  # 03:30 EDT


def test_window_in_the_spring_gap() -> None:
    gap = SessionWindow(
        id="gap_window", name="Gap", timezone=NY, start=time(2, 30), end=time(3), days=EVERY_DAY
    )
    assert gap.window_on(date(2026, 3, 8)) is None  # 02:30 → 03:30 EDT is after 03:00
    assert gap.window_on(date(2026, 3, 9)) == (utc(2026, 3, 9, 6, 30), utc(2026, 3, 9, 7))
    shifted = SessionWindow(
        id="shifted", name="Shifted", timezone=NY, start=time(2, 5), end=time(2, 55), days=EVERY_DAY
    )
    assert shifted.window_on(date(2026, 3, 8)) == (utc(2026, 3, 8, 7, 5), utc(2026, 3, 8, 7, 55))


def test_windows_between(book: SessionBook) -> None:
    orb = book.window("ny_orb_15")
    windows = orb.windows_between(local(NY, 2026, 10, 2, 9, 40), local(NY, 2026, 10, 6, 9, 31))
    assert windows == [
        (local(NY, 2026, 10, 2, 9, 30), local(NY, 2026, 10, 2, 9, 45)),  # Fri, overlapping
        (local(NY, 2026, 10, 5, 9, 30), local(NY, 2026, 10, 5, 9, 45)),  # Mon
        (local(NY, 2026, 10, 6, 9, 30), local(NY, 2026, 10, 6, 9, 45)),  # Tue, overlapping
    ]
    assert orb.windows_between(local(NY, 2026, 10, 2, 9, 45), local(NY, 2026, 10, 5, 9, 30)) == []
    asia = book.window("asia_session")
    overnight = asia.windows_between(local(NY, 2026, 10, 5, 1), local(NY, 2026, 10, 5, 2))
    assert overnight == [(local(NY, 2026, 10, 4, 18), local(NY, 2026, 10, 5, 3))]
    with pytest.raises(ValueError, match="before start"):
        orb.windows_between(utc(2026, 1, 2), utc(2026, 1, 1))


def test_session_window_validation_and_serialization() -> None:
    with pytest.raises(ValueError, match="at least one weekday"):
        SessionWindow(
            id="empty", name="x", timezone=NY, start=time(9), end=time(10), days=frozenset()
        )
    with pytest.raises(ValueError, match="tzinfo"):
        SessionWindow(
            id="aware", name="x", timezone=NY, start=time(9, tzinfo=UTC), end=time(10), days=MON_FRI
        )
    with pytest.raises(ValueError, match="unknown IANA"):
        SessionWindow(
            id="bad_tz", name="x", timezone="NY", start=time(9), end=time(10), days=MON_FRI
        )
    window = SessionWindow.from_dict(
        {"id": "ny_orb_15", "timezone": NY, "start": "09:30", "end": "09:45", "days": "MON-FRI"}
    )
    assert window.name == "ny_orb_15"  # defaults to the id
    assert window.to_dict()["days"] == ["MON", "TUE", "WED", "THU", "FRI"]
    assert SessionWindow.from_dict(window.to_dict()) == window
    with pytest.raises(ValueError, match="unknown key"):
        SessionWindow.from_dict({**window.to_dict(), "colour": "red"})
    with pytest.raises(ValueError, match="days"):
        SessionWindow.from_dict({**window.to_dict(), "days": ["MON", "FUNDAY"]})


# ════════════════════════════════════════════════════════════════════════════
# Trading calendars
# ════════════════════════════════════════════════════════════════════════════
def test_cme_daily_halt(book: SessionBook) -> None:
    cme = book.calendar("cme_globex_equity")
    assert cme.is_open(local(CHI, 2026, 10, 6, 15, 59, 59))
    assert not cme.is_open(local(CHI, 2026, 10, 6, 16))
    assert not cme.is_open(local(CHI, 2026, 10, 6, 16, 59, 59))
    assert cme.is_open(local(CHI, 2026, 10, 6, 17))
    assert cme.current_interval(local(CHI, 2026, 10, 6, 12)) == (
        local(CHI, 2026, 10, 5, 17),
        local(CHI, 2026, 10, 6, 16),
    )
    assert cme.next_open(local(CHI, 2026, 10, 6, 16, 30)) == local(CHI, 2026, 10, 6, 17)
    assert cme.next_close(local(CHI, 2026, 10, 6, 16, 30)) == local(CHI, 2026, 10, 7, 16)


def test_cme_weekend(book: SessionBook) -> None:
    cme = book.calendar("cme_globex_equity")
    assert cme.is_open(local(CHI, 2026, 10, 9, 15, 59))
    assert not cme.is_open(local(CHI, 2026, 10, 9, 16))  # Friday close
    assert not cme.is_open(local(CHI, 2026, 10, 9, 17))  # no Friday evening session
    assert not cme.is_open(local(CHI, 2026, 10, 10, 12))  # Saturday
    assert not cme.is_open(local(CHI, 2026, 10, 11, 16, 59))
    assert cme.is_open(local(CHI, 2026, 10, 11, 17))  # Sunday open


@pytest.mark.parametrize(
    ("friday_after_close", "sunday_reopen_utc", "regime"),
    [
        (local(NY, 2026, 1, 9, 17, 30), utc(2026, 1, 11, 23), "winter: 17:00 CST = 23:00 UTC"),
        (local(NY, 2026, 7, 10, 17, 30), utc(2026, 7, 12, 22), "summer: 17:00 CDT = 22:00 UTC"),
        (local(NY, 2026, 3, 6, 17, 30), utc(2026, 3, 8, 22), "DST starts that Sunday morning"),
        (local(NY, 2026, 10, 30, 17, 30), utc(2026, 11, 1, 23), "DST ends that Sunday morning"),
    ],
)
def test_next_open_friday_after_close_is_sunday_reopen(
    book: SessionBook, friday_after_close: datetime, sunday_reopen_utc: datetime, regime: str
) -> None:
    cme = book.calendar("cme_globex_equity")
    assert cme.next_open(friday_after_close) == sunday_reopen_utc, regime
    assert hhmm(sunday_reopen_utc, CHI) == "17:00"
    # The index CFD calendar mirrors CME in New York time; FX reopens at 17:00 NY.
    assert book.calendar("cfd_us_indices").next_open(friday_after_close) == sunday_reopen_utc
    fx_reopen = book.calendar("fx_otc").next_open(friday_after_close)
    metals_reopen = book.calendar("metals_otc").next_open(friday_after_close)
    assert fx_reopen is not None
    assert metals_reopen is not None
    assert hhmm(fx_reopen, NY) == "17:00"
    assert hhmm(metals_reopen, NY) == "18:00"
    assert metals_reopen - fx_reopen == timedelta(hours=1)
    assert to_local(fx_reopen, NY).weekday() == Weekday.SUN


def test_cme_christmas_holiday_cancels_the_session_closing_on_it(book: SessionBook) -> None:
    cme = book.calendar("cme_globex_equity")
    assert cme.is_open(local(CHI, 2026, 12, 24, 12, 14))
    assert not cme.is_open(local(CHI, 2026, 12, 24, 12, 15))  # early close 12:15 CT
    assert not cme.is_open(local(CHI, 2026, 12, 24, 17, 30))  # no session for Fri 12-25
    assert not cme.is_open(local(CHI, 2026, 12, 25, 10))
    assert cme.next_open(local(CHI, 2026, 12, 24, 12, 15)) == local(CHI, 2026, 12, 27, 17)
    assert cme.next_close(local(CHI, 2026, 12, 24, 9)) == local(CHI, 2026, 12, 24, 12, 15)
    assert cme.open_intervals(local(CHI, 2026, 12, 23, 18), local(CHI, 2026, 12, 28)) == [
        (local(CHI, 2026, 12, 23, 18), local(CHI, 2026, 12, 24, 12, 15)),
        (local(CHI, 2026, 12, 27, 17), local(CHI, 2026, 12, 28)),
    ]


def test_cme_new_years_day_reopens_on_the_holiday_evening(book: SessionBook) -> None:
    cme = book.calendar("cme_globex_equity")
    assert cme.is_holiday(date(2026, 1, 1))
    assert not cme.is_open(local(CHI, 2025, 12, 31, 18))  # session for 01-01 cancelled
    assert not cme.is_open(local(CHI, 2026, 1, 1, 12))
    assert cme.is_open(local(CHI, 2026, 1, 1, 17))  # trade date 01-02 opens on the holiday


def test_cme_early_closes(book: SessionBook) -> None:
    cme = book.calendar("cme_globex_equity")
    # Martin Luther King Jr. Day: halt 12:00 CT, reopen 17:00 CT for Tuesday.
    assert cme.early_close_on(date(2026, 1, 19)) == time(12)
    assert cme.is_open(local(CHI, 2026, 1, 19, 11, 59))
    assert not cme.is_open(local(CHI, 2026, 1, 19, 12))
    assert cme.next_open(local(CHI, 2026, 1, 19, 12)) == local(CHI, 2026, 1, 19, 17)
    # Thanksgiving: Thursday halt at noon, Friday early close 12:15 until Sunday.
    assert cme.next_close(local(CHI, 2026, 11, 26, 8)) == local(CHI, 2026, 11, 26, 12)
    assert cme.next_open(local(CHI, 2026, 11, 26, 13)) == local(CHI, 2026, 11, 26, 17)
    assert cme.next_close(local(CHI, 2026, 11, 26, 18)) == local(CHI, 2026, 11, 27, 12, 15)
    assert cme.next_open(local(CHI, 2026, 11, 27, 12, 15)) == local(CHI, 2026, 11, 29, 17)
    # Good Friday 2026: abbreviated session for the payrolls release, closed from 08:15 CT.
    assert cme.is_open(local(CHI, 2026, 4, 3, 7, 30))
    assert not cme.is_open(local(CHI, 2026, 4, 3, 8, 15))
    assert cme.next_open(local(CHI, 2026, 4, 3, 9)) == local(CHI, 2026, 4, 5, 17)
    assert cme.early_close_on(date(2026, 10, 6)) is None


def test_index_cfds_mirror_cme_hours(book: SessionBook) -> None:
    cme, cfd = book.calendar("cme_globex_equity"), book.calendar("cfd_us_indices")
    start, end = utc(2025, 12, 28), utc(2027, 12, 31)
    assert cme.open_intervals(start, end) == cfd.open_intervals(start, end)


def test_calendar_date_holiday_closes_the_whole_local_date() -> None:
    fx = TradingCalendar(
        id="fx_holidays",
        timezone=NY,
        intervals=weekly("SUN 17:00 - FRI 17:00"),
        holidays=frozenset({date(2026, 7, 1), date(2026, 12, 25)}),
    )
    assert fx.holiday_rule is HolidayRule.CALENDAR_DATE
    assert fx.open_intervals(local(NY, 2026, 6, 28), local(NY, 2026, 7, 4)) == [
        (local(NY, 2026, 6, 28, 17), local(NY, 2026, 7, 1)),
        (local(NY, 2026, 7, 2), local(NY, 2026, 7, 3, 17)),
    ]
    assert fx.is_open(local(NY, 2026, 12, 24, 23, 59))
    assert not fx.is_open(local(NY, 2026, 12, 25))
    assert fx.next_open(local(NY, 2026, 12, 25, 9)) == local(NY, 2026, 12, 27, 17)


def test_early_close_closes_until_the_next_scheduled_open() -> None:
    metals = TradingCalendar(
        id="metals_early",
        timezone=NY,
        intervals=weekly(
            "SUN 18:00 - MON 17:00",
            "MON 18:00 - TUE 17:00",
            "TUE 18:00 - WED 17:00",
            "WED 18:00 - THU 17:00",
            "THU 18:00 - FRI 17:00",
        ),
        early_closes=((date(2026, 11, 26), time(13, 30)),),
    )
    assert metals.is_open(local(NY, 2026, 11, 26, 13, 29))
    assert not metals.is_open(local(NY, 2026, 11, 26, 13, 30))
    assert metals.next_open(local(NY, 2026, 11, 26, 14)) == local(NY, 2026, 11, 26, 18)


def test_open_intervals_clip_and_merge() -> None:
    split = TradingCalendar(
        id="split_day",
        timezone=NY,
        intervals=weekly(
            "MON 09:00 - MON 12:00",
            "MON 12:00 - MON 15:00",  # adjacent → merged
            "MON 14:00 - MON 16:00",  # overlapping → merged
            "TUE 09:00 - TUE 10:00",
        ),
    )
    assert split.open_intervals(local(NY, 2026, 10, 5, 10), local(NY, 2026, 10, 5, 14)) == [
        (local(NY, 2026, 10, 5, 10), local(NY, 2026, 10, 5, 14))
    ]
    assert split.open_intervals(local(NY, 2026, 10, 5), local(NY, 2026, 10, 7)) == [
        (local(NY, 2026, 10, 5, 9), local(NY, 2026, 10, 5, 16)),
        (local(NY, 2026, 10, 6, 9), local(NY, 2026, 10, 6, 10)),
    ]
    assert split.current_interval(local(NY, 2026, 10, 5, 12)) == (
        local(NY, 2026, 10, 5, 9),
        local(NY, 2026, 10, 5, 16),
    )
    instant = local(NY, 2026, 10, 5, 11)
    assert split.open_intervals(instant, instant) == []
    with pytest.raises(ValueError, match="before start"):
        split.open_intervals(local(NY, 2026, 10, 6), local(NY, 2026, 10, 5))


def test_fx_week_and_metals_daily_break(book: SessionBook) -> None:
    fx = book.calendar("fx_otc")
    assert fx.open_intervals(local(NY, 2026, 10, 9, 12), local(NY, 2026, 10, 12, 12)) == [
        (local(NY, 2026, 10, 9, 12), local(NY, 2026, 10, 9, 17)),
        (local(NY, 2026, 10, 11, 17), local(NY, 2026, 10, 12, 12)),
    ]
    metals = book.calendar("metals_otc")
    week = metals.open_intervals(local(NY, 2026, 10, 11), local(NY, 2026, 10, 17))
    assert len(week) == 5
    assert all(end - start == timedelta(hours=23) for start, end in week)
    assert not metals.is_open(local(NY, 2026, 10, 13, 17, 30))
    # The weekend absorbs the DST change: Sunday's session is a normal 23 hours.
    autumn = metals.open_intervals(local(NY, 2026, 10, 31), local(NY, 2026, 11, 3))
    assert autumn[0][1] - autumn[0][0] == timedelta(hours=23)
    assert autumn[0][0] == local(NY, 2026, 11, 1, 18)


def test_us_equities_rth(book: SessionBook) -> None:
    rth = book.calendar("us_equities_rth")
    assert rth.is_open(local(NY, 2026, 10, 5, 9, 30))
    assert not rth.is_open(local(NY, 2026, 10, 5, 16))
    assert rth.next_open(local(NY, 2026, 10, 9, 16, 30)) == local(NY, 2026, 10, 12, 9, 30)


def test_crypto_is_always_open(book: SessionBook) -> None:
    crypto = book.calendar("crypto_24x7")
    ts = utc(2026, 12, 25, 3)
    assert crypto.is_open(ts)
    assert crypto.current_interval(ts) == (UNBOUNDED_START, UNBOUNDED_END)
    assert crypto.next_open(ts) == ts
    assert crypto.next_close(ts) is None
    assert crypto.open_intervals(ts, ts + timedelta(days=3)) == [(ts, ts + timedelta(days=3))]
    with pytest.raises(ClockError, match="naive"):
        crypto.is_open(wall(2026, 12, 25))


def test_next_open_and_close_when_already_open(book: SessionBook) -> None:
    fx = book.calendar("fx_otc")
    ts = local(NY, 2026, 10, 6, 12)
    assert fx.next_open(ts) == ts
    assert fx.next_close(ts) == local(NY, 2026, 10, 9, 17)
    assert fx.next_close(local(NY, 2026, 10, 10, 12)) == local(NY, 2026, 10, 16, 17)


def test_calendar_validation() -> None:
    with pytest.raises(ValueError, match="always_open"):
        TradingCalendar(
            id="mixed", timezone="UTC", always_open=True, intervals=weekly("MON 09:00 - MON 10:00")
        )
    with pytest.raises(ValueError, match="no weekly intervals"):
        TradingCalendar(id="never", timezone="UTC")
    with pytest.raises(ValueError, match="whole week"):
        TradingCalendar(
            id="all_week",
            timezone="UTC",
            intervals=weekly("SUN 17:00 - FRI 17:00", "FRI 17:00 - SUN 17:00"),
        )
    with pytest.raises(ValueError, match="both a holiday and an early close"):
        TradingCalendar(
            id="conflict",
            timezone="UTC",
            intervals=weekly("MON 09:00 - MON 10:00"),
            holidays=frozenset({date(2026, 1, 5)}),
            early_closes=((date(2026, 1, 5), time(9, 30)),),
        )
    with pytest.raises(ValueError, match="more than once"):
        TradingCalendar(
            id="duplicate",
            timezone="UTC",
            intervals=weekly("MON 09:00 - MON 10:00"),
            early_closes=((date(2026, 1, 5), time(9, 30)), (date(2026, 1, 5), time(9, 45))),
        )
    with pytest.raises(ValueError, match="unknown IANA"):
        TradingCalendar(id="bad_tz", timezone="EST5", intervals=weekly("MON 09:00 - MON 10:00"))


def test_calendar_from_dict_errors() -> None:
    base = {"id": "cal_x", "timezone": NY, "weekly": ["MON 09:00 - MON 10:00"]}
    assert TradingCalendar.from_dict(base).to_dict()["holiday_rule"] == "calendar_date"
    with pytest.raises(ValueError, match="unknown key"):
        TradingCalendar.from_dict({**base, "holiday": ["2026-01-01"]})
    with pytest.raises(ValueError, match="listed twice"):
        TradingCalendar.from_dict({**base, "holidays": ["2026-01-01", "2026-01-01"]})
    with pytest.raises(ValueError, match="holiday_rule"):
        TradingCalendar.from_dict({**base, "holiday_rule": "sometimes"})
    with pytest.raises(ValueError, match="quoted"):
        TradingCalendar.from_dict({**base, "early_closes": {"2026-01-02": 720}})
    with pytest.raises(ValueError, match="expected a list"):
        TradingCalendar.from_dict({**base, "weekly": "MON 09:00 - MON 10:00"})
    with pytest.raises(ValueError, match="true or false"):
        TradingCalendar.from_dict({**base, "always_open": "yes"})
    # Unquoted YAML dates arrive as dates. (The early close is inside the Monday
    # session: one outside the schedule would close nothing and is rejected.)
    unquoted = yaml.safe_load("holidays: [2026-01-01]\nearly_closes: {2026-01-05: '09:30'}")
    calendar = TradingCalendar.from_dict({**base, **unquoted})
    assert calendar.holidays == {date(2026, 1, 1)}
    assert calendar.early_closes == ((date(2026, 1, 5), time(9, 30)),)


# ════════════════════════════════════════════════════════════════════════════
# The book: classification, labels, documents
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    ("ts", "label"),
    [
        (local(NY, 2026, 10, 5, 9), "ny_session"),
        (local(NY, 2026, 10, 5, 16, 59), "ny_session"),
        (local(NY, 2026, 10, 5, 17, 30), OFF_HOURS),  # daily break
        (local(NY, 2026, 10, 5, 18), "asia_session"),
        (local(NY, 2026, 10, 6, 2, 59), "asia_session"),  # Monday evening's Asia
        (local(NY, 2026, 10, 6, 3), "london_session"),
        (local(NY, 2026, 10, 6, 7, 59), "london_session"),
        (local(NY, 2026, 10, 6, 8), "ny_session"),
        (local(NY, 2026, 10, 4, 18, 30), "asia_session"),  # Sunday evening
        (local(NY, 2026, 10, 9, 18, 30), OFF_HOURS),  # Friday evening
        (local(NY, 2026, 10, 10, 12), OFF_HOURS),  # Saturday
        (local(NY, 2026, 3, 9, 9), "ny_session"),  # day after the US switch
    ],
)
def test_classify(book: SessionBook, ts: datetime, label: str) -> None:
    assert book.classify(ts) == label


def test_labels_collects_every_containing_window(book: SessionBook) -> None:
    # Mon 2026-10-05 09:35 EDT = 13:35 UTC = 14:35 BST.
    assert book.labels(local(NY, 2026, 10, 5, 9, 35)) == {
        "london",
        "new_york",
        "ny_open",
        "ny_orb_15",
        "ny_orb_30",
        "ny_am_kz",
        "ny_session",
    }
    assert book.labels(local(NY, 2026, 10, 10, 12)) == frozenset()
    # 03:30 EDT on 2026-10-28 is 07:30 GMT: London has not opened yet that week.
    assert "london_open" not in book.labels(local(NY, 2026, 10, 28, 3, 30))
    assert "london_open" in book.labels(local(NY, 2026, 10, 28, 4, 30))


def test_lookups_name_the_available_ids(book: SessionBook) -> None:
    assert book.calendar("crypto_24x7").always_open
    with pytest.raises(KeyError, match=r"unknown trading calendar 'nyse'.*cme_globex_equity"):
        book.calendar("nyse")
    with pytest.raises(KeyError, match=r"unknown session window 'ny_orb_60'.*ny_orb_15"):
        book.window("ny_orb_60")
    with pytest.raises(KeyError, match=r"unknown trading-day rule 'tokyo_0700'.*ny_1700"):
        book.trading_day_rule("tokyo_0700")


def test_book_validation(book: SessionBook) -> None:
    window = book.window("ny_orb_15")
    with pytest.raises(ValueError, match="duplicate session window id 'ny_orb_15'"):
        SessionBook(windows=[window, window])
    with pytest.raises(ValueError, match="unknown session window 'asia'"):
        SessionBook(windows=[window], classification=["asia"])
    with pytest.raises(ValueError, match="twice"):
        SessionBook(windows=[window], classification=["ny_orb_15", "ny_orb_15"])
    with pytest.raises(ValueError, match="expected a mapping"):
        SessionBook.from_document({"calendars": ["cme"]})
    with pytest.raises(ValueError, match="expected a list"):
        SessionBook.from_document({"session_windows": {"id": "x"}})
    empty = SessionBook.from_document({"instruments": [], "session_classification": None})
    assert empty.classify(utc(2026, 1, 1)) == OFF_HOURS


def test_yaml_round_trips(raw_doc: dict[str, Any], book: SessionBook) -> None:
    document = book.to_document()
    assert document == raw_doc  # the YAML is written in canonical form
    assert SessionBook.from_document(document) == book
    assert yaml.safe_load(yaml.safe_dump(document)) == document


def test_yaml_contains_the_required_catalog(book: SessionBook) -> None:
    assert {calendar.id for calendar in book.calendars} == {
        "cme_globex_equity",
        "metals_otc",
        "fx_otc",
        "cfd_us_indices",
        "crypto_24x7",
        "us_equities_rth",
    }
    assert {rule.id for rule in book.trading_day_rules} == {"ny_1700", "utc_midnight"}
    assert book.classification == ("ny_session", "london_session", "asia_session")
    assert book.calendar("cme_globex_equity").holiday_rule is HolidayRule.TRADE_DATE
    cme_years = {day.year for day in book.calendar("cme_globex_equity").holidays}
    assert cme_years == {2026, 2027}


# ════════════════════════════════════════════════════════════════════════════
# Properties
# ════════════════════════════════════════════════════════════════════════════
_SECONDS_2025 = int(utc(2025, 1, 1).timestamp())
_SECONDS_2029 = int(utc(2029, 1, 1).timestamp())
instants = st.one_of(
    st.integers(_SECONDS_2025 // 60, _SECONDS_2029 // 60).map(lambda m: m * 60),
    st.integers(_SECONDS_2025, _SECONDS_2029),
).map(lambda seconds: datetime.fromtimestamp(seconds, tz=UTC))
ZONES = [
    "America/New_York",
    "America/Chicago",
    "Europe/London",
    "Australia/Sydney",
    "America/Santiago",
    "Asia/Kolkata",
    "UTC",
]


@settings(max_examples=300, deadline=None)
@given(ts=instants, window_id=st.sampled_from([w.id for w in BOOK.windows]))
def test_window_queries_agree(ts: datetime, window_id: str) -> None:
    window = BOOK.window(window_id)
    found = window.window_at(ts)
    assert window.contains(ts) == (found is not None)
    around = window.windows_between(ts - timedelta(days=2), ts + timedelta(days=2))
    containing = [span for span in around if span[0] <= ts < span[1]]
    assert containing == ([found] if found is not None else [])


@settings(max_examples=300, deadline=None)
@given(
    ts=instants,
    tz=st.sampled_from(ZONES),
    rollover=st.times().map(lambda t: t.replace(second=0, microsecond=0)),
)
def test_trading_day_lies_within_its_bounds(ts: datetime, tz: str, rollover: time) -> None:
    rule = TradingDayRule(id="rule_x", timezone=tz, rollover=rollover)
    day = rule.trading_day(ts)
    start, end = rule.day_bounds(day)
    assert start <= ts < end
    assert rule.day_bounds(day - timedelta(days=1))[1] == start  # contiguous partition
    assert timedelta(hours=22) <= end - start <= timedelta(hours=26)


@settings(max_examples=150, deadline=None)
@given(ts=instants, calendar_id=st.sampled_from([c.id for c in BOOK.calendars]))
def test_calendar_queries_agree(ts: datetime, calendar_id: str) -> None:
    calendar = BOOK.calendar(calendar_id)
    is_open = calendar.is_open(ts)
    assert is_open == (calendar.current_interval(ts) is not None)
    nearby = calendar.open_intervals(ts - timedelta(days=3), ts + timedelta(days=3))
    assert is_open == any(start <= ts < end for start, end in nearby)
    for (_, end), (start, _) in pairwise(nearby):
        assert end < start  # sorted, disjoint and never adjacent (merged)
    reopen = calendar.next_open(ts)
    assert reopen is not None
    assert reopen >= ts
    assert calendar.is_open(reopen)
    assert (reopen == ts) == is_open
    close = calendar.next_close(ts)
    if calendar.always_open:
        assert close is None
    else:
        assert close is not None
        assert close > ts
        assert not calendar.is_open(close)


@settings(max_examples=200, deadline=None)
@given(ts=instants)
def test_classification_windows_never_overlap(ts: datetime) -> None:
    hits = BOOK.labels(ts) & set(BOOK.classification)
    assert len(hits) <= 1
    assert BOOK.classify(ts) == (next(iter(hits)) if hits else OFF_HOURS)


@settings(max_examples=200, deadline=None)
@given(ts=instants)
def test_cfd_calendar_matches_cme_at_every_instant(ts: datetime) -> None:
    cme, cfd = BOOK.calendar("cme_globex_equity"), BOOK.calendar("cfd_us_indices")
    assert cme.is_open(ts) == cfd.is_open(ts)


@settings(max_examples=300, deadline=None)
@given(
    day=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    at=st.times(),
    tz=st.sampled_from(ZONES),
)
def test_to_utc_round_trips_or_shifts_forward(day: date, at: time, tz: str) -> None:
    wall_clock = datetime.combine(day, at)
    instant = to_utc(wall_clock, tz)
    back = to_local(instant, tz).replace(tzinfo=None, fold=0)
    if back == wall_clock:
        # The time exists; if it is ambiguous, the result is the first occurrence
        # (the second one is an hour later, so nothing an hour earlier reads the same).
        assert to_local(instant - timedelta(hours=1), tz).replace(tzinfo=None) != wall_clock
    else:
        # A nonexistent time is shifted forward by the gap (one hour in these zones).
        assert back - wall_clock == timedelta(hours=1)


# ════════════════════════════════════════════════════════════════════════════
# Review: holiday / early-close semantics with adjacent sessions, validation
# ════════════════════════════════════════════════════════════════════════════
DAILY_FX_SESSIONS = weekly(
    "SUN 17:00 - MON 17:00",
    "MON 17:00 - TUE 17:00",
    "TUE 17:00 - WED 17:00",
    "WED 17:00 - THU 17:00",
    "THU 17:00 - FRI 17:00",
)


def test_trade_date_holiday_cancels_only_the_adjacent_session_closing_on_it() -> None:
    """Touching weekly intervals are separate sessions: a trade-date holiday cancels the
    one that closes on it, not the whole merged week (and never nothing)."""
    wednesday = TradingCalendar(
        id="fx_daily_wed",
        timezone=NY,
        intervals=DAILY_FX_SESSIONS,
        holiday_rule=HolidayRule.TRADE_DATE,
        holidays=frozenset({date(2026, 10, 7)}),
    )
    assert wednesday.is_open(local(NY, 2026, 10, 6, 16, 59))
    assert not wednesday.is_open(local(NY, 2026, 10, 6, 17))  # Tue 17:00 → Wed 17:00 cancelled
    assert not wednesday.is_open(local(NY, 2026, 10, 7, 12))
    assert wednesday.is_open(local(NY, 2026, 10, 7, 17))  # trade date Thu opens on the holiday
    assert wednesday.open_intervals(local(NY, 2026, 10, 4), local(NY, 2026, 10, 10)) == [
        (local(NY, 2026, 10, 4, 17), local(NY, 2026, 10, 6, 17)),
        (local(NY, 2026, 10, 7, 17), local(NY, 2026, 10, 9, 17)),
    ]
    friday = TradingCalendar(
        id="fx_daily_fri",
        timezone=NY,
        intervals=DAILY_FX_SESSIONS,
        holiday_rule=HolidayRule.TRADE_DATE,
        holidays=frozenset({date(2026, 10, 9)}),
    )
    assert friday.is_open(local(NY, 2026, 10, 5, 12))  # Monday is unaffected
    assert friday.next_close(local(NY, 2026, 10, 5, 12)) == local(NY, 2026, 10, 8, 17)


def test_early_close_reopens_at_the_next_session_open_of_adjacent_sessions() -> None:
    fx = TradingCalendar(
        id="fx_daily_early",
        timezone=NY,
        intervals=DAILY_FX_SESSIONS,
        early_closes=((date(2026, 11, 26), time(13)),),  # Thanksgiving
    )
    assert not fx.is_open(local(NY, 2026, 11, 26, 13))
    assert fx.next_open(local(NY, 2026, 11, 26, 14)) == local(NY, 2026, 11, 26, 17)
    # An interval that opens *inside* another one is not a session open.
    nested = TradingCalendar(
        id="nested",
        timezone=NY,
        intervals=weekly("MON 09:00 - MON 16:00", "MON 12:00 - MON 13:00"),
        early_closes=((date(2026, 10, 5), time(10)),),
    )
    assert not nested.is_open(local(NY, 2026, 10, 5, 12, 30))
    assert nested.next_open(local(NY, 2026, 10, 5, 10)) == local(NY, 2026, 10, 12, 9)


def test_trade_date_holiday_that_cancels_no_session_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"2026-10-07.*WED.*would close nothing"):
        TradingCalendar(
            id="fx_week",
            timezone=NY,
            intervals=weekly("SUN 17:00 - FRI 17:00"),  # one session, closing on Friday
            holiday_rule=HolidayRule.TRADE_DATE,
            holidays=frozenset({date(2026, 10, 7)}),
        )
    # A session closing at 00:00 belongs to the day before.
    late = TradingCalendar(
        id="late_session",
        timezone=NY,
        intervals=weekly("MON 18:00 - TUE 00:00"),
        holiday_rule=HolidayRule.TRADE_DATE,
        holidays=frozenset({date(2026, 10, 5)}),
    )
    assert not late.is_open(local(NY, 2026, 10, 5, 20))
    with pytest.raises(ValueError, match="would close nothing"):
        TradingCalendar.from_dict(
            {**late.to_dict(), "id": "late_session_2", "holidays": ["2026-10-06"]}
        )


@pytest.mark.parametrize(
    ("early_close", "message"),
    [
        ((date(2026, 10, 10), time(12)), r"2026-10-10 \(SAT\) 12:00.*outside the weekly schedule"),
        ((date(2026, 10, 6), time(16, 30)), "outside the weekly schedule"),  # in the daily halt
        ((date(2026, 10, 6), time(16)), "outside the weekly schedule"),  # at the close itself
        ((date(2026, 12, 24), time(18)), r"cancelled by the holiday 2026-12-25"),
    ],
)
def test_early_close_that_would_close_nothing_is_rejected(
    early_close: tuple[date, time], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        TradingCalendar(
            id="cme_like",
            timezone=CHI,
            intervals=weekly(
                "SUN 17:00 - MON 16:00",
                "MON 17:00 - TUE 16:00",
                "TUE 17:00 - WED 16:00",
                "WED 17:00 - THU 16:00",
                "THU 17:00 - FRI 16:00",
            ),
            holiday_rule=HolidayRule.TRADE_DATE,
            holidays=frozenset({date(2026, 12, 25)}),
            early_closes=(early_close,),
        )


def test_windows_between_an_empty_range_is_empty(book: SessionBook) -> None:
    orb = book.window("ny_orb_15")
    inside = local(NY, 2026, 10, 5, 9, 40)
    assert orb.contains(inside)
    assert orb.windows_between(inside, inside) == []  # like open_intervals(t, t)
    assert book.calendar("fx_otc").open_intervals(inside, inside) == []


@pytest.mark.parametrize(
    "build",
    [
        lambda: TradingCalendar(
            id="str_holiday",
            timezone=NY,
            intervals=weekly("MON 09:30 - MON 16:00"),
            holidays=frozenset({"2026-12-25"}),  # type: ignore[arg-type]
        ),
        lambda: TradingCalendar(
            id="str_close_time",
            timezone=NY,
            intervals=weekly("MON 09:30 - MON 16:00"),
            early_closes={date(2026, 10, 5): "12:00"},  # type: ignore[arg-type]
        ),
        lambda: TradingCalendar(
            id="str_close_date",
            timezone=NY,
            intervals=weekly("MON 09:30 - MON 16:00"),
            early_closes={"2026-10-05": time(12)},  # type: ignore[arg-type]
        ),
        lambda: TradingCalendar(
            id="bad_pairs",
            timezone=NY,
            intervals=weekly("MON 09:30 - MON 16:00"),
            early_closes=(date(2026, 10, 5),),  # type: ignore[arg-type]
        ),
        lambda: TradingCalendar(
            id="bad_interval",
            timezone=NY,
            intervals=(42,),  # type: ignore[arg-type]
        ),
        lambda: TradingCalendar(
            id="bad_flag",
            timezone=NY,
            intervals=weekly("MON 09:30 - MON 16:00"),
            always_open="no",  # type: ignore[arg-type]
        ),
        lambda: WeeklyInterval(Weekday.MON, "09:00", Weekday.MON, time(10)),  # type: ignore[arg-type]
        lambda: SessionWindow(
            id="str_start",
            name="x",
            timezone=NY,
            start="09:00",  # type: ignore[arg-type]
            end=time(10),
            days=MON_FRI,
        ),
        lambda: TradingDayRule(id="str_rollover", timezone=NY, rollover="17:00"),  # type: ignore[arg-type]
        lambda: SessionBook(classification="ny_session"),
    ],
)
def test_constructors_reject_wrong_types_with_value_errors(build: Any) -> None:
    with pytest.raises(ValueError, match=r"expected|must be"):
        build()


def test_constructors_normalise_friendly_inputs() -> None:
    text_intervals: Any = ("MON 09:30 - MON 16:00",)
    calendar = TradingCalendar(id="text_intervals", timezone=NY, intervals=text_intervals)
    assert calendar.intervals == weekly("MON 09:30 - MON 16:00")
    window = SessionWindow(
        id="range_days",
        name="x",
        timezone=NY,
        start=time(9),
        end=time(10),
        days="MON-FRI",  # type: ignore[arg-type]
    )
    assert window.days == MON_FRI


def test_date_arguments_reject_datetimes(book: SessionBook) -> None:
    """A datetime *is* a date in Python; silently taking its (UTC) date picks the wrong
    local day, so the date-based methods refuse it."""
    instant = utc(2026, 10, 6, 2)  # Monday 22:00 in New York
    with pytest.raises(TypeError, match="window_at"):
        book.window("ny_orb_15").window_on(instant)
    with pytest.raises(TypeError, match="trading_day"):
        book.trading_day_rule("ny_1700").day_bounds(instant)
    cme = book.calendar("cme_globex_equity")
    with pytest.raises(TypeError, match="date"):
        cme.is_holiday(utc(2026, 12, 25))
    with pytest.raises(TypeError, match="date"):
        cme.early_close_on(utc(2026, 11, 26))


@pytest.mark.parametrize("raw", ["١٧:٠٠", "１７:００"])
def test_parse_time_accepts_ascii_digits_only(raw: str) -> None:
    with pytest.raises(ValueError, match="time"):
        parse_time(raw)


def test_parse_date_accepts_ascii_digits_only() -> None:
    with pytest.raises(ValueError, match="date"):
        parse_date("٢٠٢٦-١٢-٢٥")


# ── an independent, brute-force model of the calendar rules ───────────────
def _reference_is_open(calendar: TradingCalendar, ts: datetime) -> bool:
    """Literal transcription of the documented rules, one instant at a time."""
    if calendar.always_open:
        return True
    tz = ZoneInfo(calendar.timezone)
    week = timedelta(days=7)
    monday = datetime.combine(ts.astimezone(tz).date(), time(0))
    monday -= timedelta(days=monday.weekday())

    def trade_date(close: datetime) -> date:
        return (close - timedelta(days=1)).date() if close.time() == time(0) else close.date()

    scheduled = False
    for interval in calendar.intervals:
        for k in (-2, -1, 0, 1):
            opened = monday + k * week + interval.open_offset
            closed = opened + interval.duration
            if (
                calendar.holiday_rule is HolidayRule.TRADE_DATE
                and trade_date(closed) in calendar.holidays
            ):
                continue
            scheduled |= to_utc(opened, tz) <= ts < to_utc(closed, tz)
    if not scheduled:
        return False
    if calendar.holiday_rule is HolidayRule.CALENDAR_DATE:
        for day in calendar.holidays:
            day_start = to_utc(datetime.combine(day, time(0)), tz)
            if day_start <= ts < to_utc(datetime.combine(day + timedelta(days=1), time(0)), tz):
                return False
    session_opens = [
        interval.open_offset
        for interval in calendar.intervals
        if not any(
            other.open_offset < at < other.open_offset + other.duration
            for other in calendar.intervals
            for at in (interval.open_offset, interval.open_offset + week)
        )
    ]
    for day, at in calendar.early_closes:
        halt = datetime.combine(day, at)
        base = datetime.combine(day - timedelta(days=day.weekday()), time(0))
        reopen = min(
            base + k * week + offset
            for k in (-1, 0, 1, 2)
            for offset in session_opens
            if base + k * week + offset > halt
        )
        if to_utc(halt, tz) <= ts < to_utc(reopen, tz):
            return False
    return True


_quarter_hours = st.builds(time, st.integers(0, 23), st.sampled_from([0, 15, 30, 45]))


@st.composite
def _weekly_intervals(draw: st.DrawFn) -> WeeklyInterval:
    open_day, close_day = draw(st.sampled_from(list(Weekday))), draw(st.sampled_from(list(Weekday)))
    open_time, close_time = draw(_quarter_hours), draw(_quarter_hours)
    assume((open_day, open_time) != (close_day, close_time))  # zero length is rejected
    interval = WeeklyInterval(open_day, open_time, close_day, close_time)
    assume(interval.duration <= timedelta(days=3))
    return interval


# Exceptions and probes live in a window that holds the US (03-08), UK (03-29),
# Lord Howe and Santiago (04-05) DST changes, so they interact with each other.
_FIRST_DAY, _LAST_DAY = date(2026, 3, 1), date(2026, 4, 30)
_exception_days = st.dates(min_value=_FIRST_DAY, max_value=_LAST_DAY)


def _time_of_day(week_offset: timedelta) -> time:
    minutes = int((week_offset % timedelta(days=1)).total_seconds()) // 60
    return time(minutes // 60, minutes % 60)


@st.composite
def _touching_sessions(draw: st.DrawFn) -> tuple[WeeklyInterval, ...]:
    """2-5 sessions, each opening where the previous one closes (FX-style daily sessions)."""
    cursor = timedelta(days=draw(st.integers(0, 6)), minutes=15 * draw(st.integers(0, 95)))
    intervals = []
    for _ in range(draw(st.integers(2, 5))):
        length = timedelta(minutes=15 * draw(st.integers(4, 4 * 30)))
        close = cursor + length
        intervals.append(
            WeeklyInterval(
                Weekday((cursor // timedelta(days=1)) % 7),
                _time_of_day(cursor),
                Weekday((close // timedelta(days=1)) % 7),
                _time_of_day(close),
            )
        )
        cursor = close
    return tuple(intervals)


@st.composite
def _random_calendars(draw: st.DrawFn) -> TradingCalendar:
    tz = draw(st.sampled_from([*ZONES, "Australia/Lord_Howe"]))
    intervals = draw(
        st.one_of(
            st.lists(_weekly_intervals(), min_size=1, max_size=4).map(tuple),
            _touching_sessions(),
        )
    )
    rule = draw(st.sampled_from(list(HolidayRule)))
    try:
        base = TradingCalendar(id="random_cal", timezone=tz, intervals=intervals, holiday_rule=rule)
    except ValueError:
        assume(False)
    holidays: set[date] = set()
    for day in draw(st.lists(_exception_days, max_size=6)):
        try:
            replace(base, holidays=frozenset({day}))
            holidays.add(day)
        except ValueError:
            pass  # a trade-date holiday on a day no session closes
    early: dict[date, time] = {}
    for _ in range(draw(st.integers(0, 6))):
        # A wall-clock instant inside a configured session.
        interval = draw(st.sampled_from(intervals))
        week = (
            _FIRST_DAY
            - timedelta(days=_FIRST_DAY.weekday())
            + timedelta(weeks=draw(st.integers(0, 8)))
        )
        quarters = interval.duration // timedelta(minutes=15)
        halt = (
            datetime.combine(week, time(0))
            + interval.open_offset
            + timedelta(minutes=15 * draw(st.integers(0, quarters - 1)))
        )
        if halt.date() in holidays or halt.date() in early:
            continue
        try:
            replace(base, holidays=frozenset(holidays), early_closes=((halt.date(), halt.time()),))
            early[halt.date()] = halt.time()
        except ValueError:
            pass  # inside a session a trade-date holiday already cancels
    return replace(base, holidays=frozenset(holidays), early_closes=tuple(early.items()))


@settings(max_examples=150, deadline=None)
@given(calendar=_random_calendars(), data=st.data())
def test_random_calendars_match_the_reference_model(
    calendar: TradingCalendar, data: st.DataObject
) -> None:
    """Holidays, early closes, touching and overlapping sessions and DST against an
    independent instant-by-instant model of the documented rules."""
    start, end = utc(2026, 2, 20), utc(2026, 5, 10)
    spans = calendar.open_intervals(start, end)
    probes = st.integers(0, (end - start) // timedelta(minutes=15) - 1).map(
        lambda q: start + timedelta(minutes=15 * q)
    ) | st.integers(0, int((end - start).total_seconds()) - 1).map(
        lambda s: start + timedelta(seconds=s)
    )
    for ts in data.draw(st.lists(probes, min_size=40, max_size=40)):
        expected = _reference_is_open(calendar, ts)
        assert calendar.is_open(ts) == expected, ts
        assert any(s <= ts < e for s, e in spans) == expected, ts
        reopen = calendar.next_open(ts)
        assert reopen is not None
        assert _reference_is_open(calendar, reopen), ts
        if reopen > ts:
            assert not _reference_is_open(calendar, reopen - timedelta(seconds=1)), ts
        close = calendar.next_close(ts)
        assert close is not None
        assert close > ts
        assert not _reference_is_open(calendar, close), ts


# ════════════════════════════════════════════════════════════════════════════
# Review (2): zones, document readers, ordering, untested branches
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", ["localtime", "posixrules", "Factory"])
def test_host_dependent_pseudo_zones_are_rejected(name: str) -> None:
    """zoneinfo finds these files in the system zone directory, but ``localtime`` is the
    *host's* zone (the same YAML would mean different hours on different machines) and
    the others are placeholders, not IANA zones."""
    with pytest.raises(ValueError, match="not an IANA time zone"):
        zone(name)
    with pytest.raises(ValueError, match="not an IANA time zone"):
        TradingDayRule.from_dict({"id": "host_day", "timezone": name, "rollover": "17:00"})


@pytest.mark.parametrize("value", [date(2026, 3, 8), "2026-03-08 02:30", 1_772_951_400])
def test_to_utc_rejects_values_that_are_not_datetimes(value: Any) -> None:
    with pytest.raises(TypeError, match="naive local datetime"):
        to_utc(value, NY)


@pytest.mark.parametrize("raw", [b"\x00\x01", {"MON": True}, bytearray(b"\x00")])
def test_parse_weekdays_rejects_bytes_and_mappings(raw: Any) -> None:
    with pytest.raises(ValueError, match="weekdays must be"):
        parse_weekdays(raw)


@pytest.mark.parametrize(
    ("reader", "entry", "key"),
    [
        (
            TradingDayRule.from_dict,
            {"id": "day_rule", "timezone": NY, "rollover": "17:00"},
            "description",
        ),
        (
            TradingCalendar.from_dict,
            {"id": "cal", "timezone": NY, "weekly": ["MON 09:30 - MON 16:00"]},
            "description",
        ),
        (
            SessionWindow.from_dict,
            {"id": "win", "timezone": NY, "start": "09:00", "end": "10:00", "days": ["MON"]},
            "description",
        ),
        (
            SessionWindow.from_dict,
            {"id": "win", "timezone": NY, "start": "09:00", "end": "10:00", "days": ["MON"]},
            "name",
        ),
    ],
)
@pytest.mark.parametrize("bad", [False, 0, []])
def test_document_text_fields_report_wrong_types(
    reader: Any, entry: dict[str, Any], key: str, bad: Any
) -> None:
    """``description: false`` or ``name: 0`` is a typo; it used to be swallowed
    (read as "" / the id) by ``data.get(key) or default``."""
    with pytest.raises(ValueError, match=rf"{key}: expected a string"):
        reader({**entry, key: bad})
    # Only a missing or null value takes the default.
    assert reader({**entry, key: None}) == reader(entry)


def test_window_name_defaults_to_the_id_and_must_not_be_blank() -> None:
    entry = {"id": "ny_win", "timezone": NY, "start": "09:00", "end": "10:00", "days": ["MON"]}
    assert SessionWindow.from_dict(entry).name == "ny_win"
    assert SessionWindow.from_dict({**entry, "name": None}).name == "ny_win"
    for blank in ("", "   "):
        with pytest.raises(ValueError, match="name must not be blank"):
            SessionWindow.from_dict({**entry, "name": blank})
        # A blank name would not survive from_dict(to_dict()) (it reads back as the id).
        with pytest.raises(ValueError, match="name must not be blank"):
            SessionWindow(
                id="ny_win", name=blank, timezone=NY, start=time(9), end=time(10), days=MON_FRI
            )


def test_calendar_early_closes_document_forms() -> None:
    base = {"id": "early_forms", "timezone": NY, "weekly": ["MON 09:30 - MON 16:00"]}
    plain = TradingCalendar.from_dict(base)
    assert TradingCalendar.from_dict({**base, "early_closes": None}) == plain
    assert TradingCalendar.from_dict({**base, "early_closes": []}) == plain
    for bad in (0, False, "2026-10-05 12:00", [["2026-10-05", "12:00"]]):
        with pytest.raises(ValueError, match="early_closes: expected a mapping"):
            TradingCalendar.from_dict({**base, "early_closes": bad})
    # The same day written once as a YAML date and once as a string.
    with pytest.raises(ValueError, match="2026-10-05 is listed twice"):
        TradingCalendar.from_dict(
            {**base, "early_closes": {date(2026, 10, 5): "12:00", "2026-10-05": "13:00"}}
        )


def test_classification_must_be_ordered(book: SessionBook) -> None:
    """A set has no order and string hashes are salted per process, so overlapping
    classification windows would be labelled differently from run to run."""
    windows = [book.window("new_york"), book.window("ny_orb_15")]
    for unordered in ({"ny_orb_15", "new_york"}, frozenset({"new_york"}), {"new_york": 1}):
        with pytest.raises(ValueError, match="ordered list"):
            SessionBook(windows=windows, classification=unordered)  # type: ignore[arg-type]
    ordered = SessionBook(windows=windows, classification=("ny_orb_15", "new_york"))
    assert ordered.classify(local(NY, 2026, 10, 5, 9, 40)) == "ny_orb_15"
    assert ordered.classify(local(NY, 2026, 10, 5, 12)) == "new_york"
    assert SessionBook(windows=windows, classification=["new_york"]).classification == ("new_york",)


def test_constructor_validation_branches() -> None:
    with pytest.raises(ValueError, match="holiday_rule must be one of calendar_date, trade_date"):
        TradingCalendar(
            id="bad_rule",
            timezone=NY,
            intervals=weekly("MON 09:30 - MON 16:00"),
            holiday_rule="exchange",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="intervals must be a list"):
        TradingCalendar(id="bad_list", timezone=NY, intervals=42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="intervals must be a list"):
        TradingCalendar(id="bad_list", timezone=NY, intervals="MON 09:30 - MON 16:00")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"session window 'bad_days': days: unknown weekday"):
        SessionWindow(
            id="bad_days",
            name="x",
            timezone=NY,
            start=time(9),
            end=time(10),
            days=frozenset({"FUNDAY"}),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="sub-second"):
        TradingDayRule(id="sub_second", timezone=NY, rollover=time(17, 0, 0, 1))
    with pytest.raises(ValueError, match="description: expected a string"):
        TradingDayRule(id="bad_text", timezone=NY, rollover=time(17), description=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"takes a datetime\.date"):
        BOOK.window("ny_orb_15").window_on("2026-10-05")  # type: ignore[arg-type]


def test_times_with_seconds_round_trip() -> None:
    rule = TradingDayRule.from_dict({"id": "odd_rollover", "timezone": NY, "rollover": "16:59:30"})
    assert rule.rollover == time(16, 59, 30)
    assert rule.to_dict()["rollover"] == "16:59:30"
    assert TradingDayRule.from_dict(rule.to_dict()) == rule
    interval = WeeklyInterval.parse("SUN 17:00:15 - MON 16:00:45")
    assert str(interval) == "SUN 17:00:15 - MON 16:00:45"
    assert WeeklyInterval.parse(str(interval)) == interval


def test_book_equality_and_repr(book: SessionBook) -> None:
    assert book != "a session book"
    assert book.__eq__(42) is NotImplemented
    text = repr(book)
    assert "cme_globex_equity" in text
    assert "ny_1700" in text
    assert "ny_orb_15" in text
    other = SessionBook(windows=[book.window("ny_orb_15")])
    assert other != book


def test_week_memo_eviction_keeps_answers_correct() -> None:
    """Point queries are memoised per local week (bounded); sweeping more weeks than the
    memo holds evicts it, and every answer must still match the range query."""
    calendar = TradingCalendar(
        id="memo_sweep",
        timezone=NY,
        intervals=weekly("MON 09:30 - MON 16:00", "FRI 22:00 - MON 01:00"),
        holidays=frozenset({date(2026, 10, 5)}),
    )
    probe = local(NY, 2026, 10, 12, 10)  # a regular Monday morning: open
    assert calendar.is_open(probe)
    start = utc(2010, 1, 4, 15)
    for week in range(1_100):  # > the per-calendar memo size
        ts = start + timedelta(weeks=week)
        expected = any(s <= ts < e for s, e in calendar.open_intervals(ts - _DAY, ts + _DAY))
        assert calendar.is_open(ts) == expected, ts
    assert calendar.is_open(probe)
    assert not calendar.is_open(local(NY, 2026, 10, 5, 10))  # the holiday
    assert calendar.next_open(local(NY, 2026, 10, 5, 10)) == local(NY, 2026, 10, 9, 22)


_DAY = timedelta(days=1)

"""Trading calendars, trading-day rules, session windows and DST.

Reference dates (2026): US DST starts 2026-03-08 and ends 2026-11-01; UK BST
starts 2026-03-29 and ends 2026-10-25. Between those pairs of dates London
and New York are only four hours apart instead of five.
"""

from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from hypothesis import given, settings
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
    unquoted = yaml.safe_load("holidays: [2026-01-01]\nearly_closes: {2026-01-02: '12:00'}")
    calendar = TradingCalendar.from_dict({**base, **unquoted})
    assert calendar.holidays == {date(2026, 1, 1)}
    assert calendar.early_closes == ((date(2026, 1, 2), time(12)),)


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

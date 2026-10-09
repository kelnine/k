"""Trading calendars, trading-day rules, session windows and time zones.

Markets keep local hours: CME equity-index futures trade Sunday 17:00 →
Friday 16:00 *Chicago* time with a daily halt, spot metals follow New York,
the London session starts at 08:00 *London* time, crypto never closes. The
UK and the US switch daylight-saving time on different dates, so any rule
written as a fixed UTC offset is wrong for several weeks a year. This module
therefore stores every rule in local wall-clock time together with an IANA
zone and converts with :mod:`zoneinfo`; every instant going in or coming out
is timezone-aware UTC (see :func:`kterminal.core.clock.ensure_utc`).

Four concepts (``docs/11-instruments-sessions-costs.md`` §11.3):

``TradingCalendar``
    When a venue/instrument is open: weekly local intervals (which may wrap
    across days and the week end), plus holiday closures and early closes, or
    simply ``always_open`` (crypto).
``TradingDayRule``
    Which trading day an instant belongs to (daily P&L, daily loss limits,
    daily bars): a new day starts at the local ``rollover`` time, e.g. 17:00
    New York (``ny_1700``) or UTC midnight (``utc_midnight``).
``SessionWindow``
    Named local windows that strategies and analytics use: ORB ranges, kill
    zones, the London / New York sessions. A window is always evaluated in its
    *own* zone, so ``london_open`` is 08:00 London all year and moves between
    03:00 and 04:00 New York time.
``SessionBook``
    The configured set of all of the above, plus the ordered *classification*
    list that labels each trade's session for analytics.

Local wall-clock rules
----------------------
:func:`to_utc` defines how a local wall-clock time becomes an instant, and
every rule in this module goes through it:

* a time that does not exist (the spring-forward gap, e.g. 02:30 New York on
  2026-03-08) is shifted **forward by the gap** (→ 03:30 EDT);
* an ambiguous time (the autumn fall-back hour, e.g. 01:30 New York on
  2026-11-01) resolves to its **first** occurrence (01:30 EDT, ``fold=0``).

Naive ``datetime`` objects appear here only as *local wall-clock values*
(the input of :func:`to_utc` and internal calendar arithmetic); they never
leave the module as timestamps.

Holidays
--------
``holidays`` and ``early_closes`` are explicit dates in configuration (they
change every year and must be reviewed annually). Every configured weekly
interval is a *session*: holidays and early closes act on the sessions as
configured, and only the reported open periods are merged. Two touching
intervals (``SUN 17:00 - MON 17:00``, ``MON 17:00 - TUE 17:00``) are therefore
two daily sessions, although the market never closes between them.

Two holiday rules exist:

* ``calendar_date`` (default): the market is closed for the whole *local*
  calendar date, 00:00–24:00 in the calendar's zone.
* ``trade_date``: for exchanges whose session for a trade date opens the
  evening before (CME Globex: Thursday 17:00 → Friday 16:00 is Friday's
  session), a holiday cancels every session that *closes* on that local date
  (a session closing at 00:00 belongs to the day before). The evening session
  that opens on the holiday itself (for the next trade date) still takes
  place. This is exactly how CME publishes "Christmas Day: closed" or "New
  Year's Day: closed, reopens 17:00 CT".

An early close ``(date, t)`` closes the market from local ``t`` on that date
until the next *session open* after it, whatever the holiday rule. A session
open is the start of a configured interval that no other interval already
covers. With touching daily sessions the market reopens at the next daily
session; an interval nested inside another one does not reopen it.

Exceptions that would change nothing are configuration errors, because they
usually mean a wrong date in the yearly list, so they are rejected:

* a ``trade_date`` holiday on a weekday on which no session closes;
* an early close outside every scheduled session;
* an early close inside a session that a ``trade_date`` holiday already
  cancels.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import IntEnum, StrEnum
from typing import Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kterminal.core.clock import ensure_utc
from kterminal.domain.instruments import ID_PATTERN

OFF_HOURS = "off_hours"
"""Label :meth:`SessionBook.classify` returns when no classification window contains an instant."""

UNBOUNDED_START = datetime(1, 1, 1, tzinfo=UTC)
UNBOUNDED_END = datetime(9999, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC)
"""Bounds :meth:`TradingCalendar.current_interval` reports for an ``always_open`` calendar."""

_DAY = timedelta(days=1)
_WEEK = timedelta(days=7)
_WEEK_CACHE_SIZE = 1_024  # weeks of merged open spans memoised per calendar
_MIDNIGHT = time(0, 0)
# ASCII only: ``\d`` alone would also accept Arabic-Indic or full-width digits.
_TIME_TEXT = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", re.ASCII)
_DATE_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)
_INTERVAL_TEXT = re.compile(
    r"^\s*([A-Za-z]+)\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:->|→|–|-)\s*"
    r"([A-Za-z]+)\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*$",
    re.ASCII,
)


# ── weekdays ─────────────────────────────────────────────────────────────────
class Weekday(IntEnum):
    """Day of the week, numbered like :meth:`datetime.date.weekday` (Monday = 0)."""

    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6

    def __str__(self) -> str:
        return self.name

    @classmethod
    def parse(cls, raw: "str | int | Weekday") -> "Weekday":
        """``"MON"`` … ``"SUN"`` (any case, full names accepted) or 0–6."""
        if isinstance(raw, Weekday):
            return raw
        if isinstance(raw, int) and not isinstance(raw, bool):
            if 0 <= raw <= 6:
                return cls(raw)
            raise ValueError(f"weekday number must be 0 (MON) … 6 (SUN), got {raw}")
        if isinstance(raw, str):
            key = raw.strip().upper()
            for day in cls:
                if key in (day.name, _FULL_DAY_NAMES[day]):
                    return day
        raise ValueError(f"unknown weekday {raw!r}; use MON, TUE, WED, THU, FRI, SAT or SUN")

    @classmethod
    def of(cls, day: date) -> "Weekday":
        return cls(day.weekday())


_FULL_DAY_NAMES = {
    Weekday.MON: "MONDAY",
    Weekday.TUE: "TUESDAY",
    Weekday.WED: "WEDNESDAY",
    Weekday.THU: "THURSDAY",
    Weekday.FRI: "FRIDAY",
    Weekday.SAT: "SATURDAY",
    Weekday.SUN: "SUNDAY",
}
WEEKDAYS_MON_FRI = frozenset({Weekday.MON, Weekday.TUE, Weekday.WED, Weekday.THU, Weekday.FRI})


def parse_weekdays(raw: object) -> frozenset[Weekday]:
    """A set of weekdays from a list (``[MON, TUE]``) or a range string (``"MON-FRI"``).

    Ranges follow the week order and may wrap: ``"SUN-THU"`` is Sunday through
    Thursday.
    """
    if isinstance(raw, str):
        text = raw.strip()
        if "-" in text:
            first_text, last_text = (part.strip() for part in text.split("-", 1))
            first, last = Weekday.parse(first_text), Weekday.parse(last_text)
            span = (last - first) % 7
            return frozenset(Weekday((first + offset) % 7) for offset in range(span + 1))
        return frozenset(Weekday.parse(part) for part in text.split(",") if part.strip())
    # bytes iterate as small ints (b"\x00\x01" would read as MON, TUE) and a
    # mapping as its keys: both are type errors, not weekday lists.
    if isinstance(raw, Iterable) and not isinstance(raw, bytes | bytearray | Mapping):
        return frozenset(Weekday.parse(item) for item in raw)
    raise ValueError(
        f"weekdays must be a list like [MON, TUE] or a range like 'MON-FRI', got {raw!r}"
    )


def week_order(days: Iterable[Weekday]) -> list[Weekday]:
    """``days`` in natural reading order: starting at the first day of the longest
    consecutive run, so Sunday-Thursday reads ``SUN, MON, TUE, WED, THU``."""
    present = frozenset(days)
    if len(present) in (0, 7):
        return sorted(present)

    def run_length(first: Weekday) -> int:
        length = 0
        while Weekday((first + length) % 7) in present:
            length += 1
        return length

    starts = [day for day in present if Weekday((day - 1) % 7) not in present]
    first = max(starts, key=lambda day: (run_length(day), -day))
    return [
        Weekday((first + step) % 7) for step in range(7) if Weekday((first + step) % 7) in present
    ]


# ── time zones and wall-clock conversion ─────────────────────────────────────
# Files that zoneinfo finds in the system time-zone directory but that are not
# IANA zones: ``localtime`` is a symlink to the *host's* zone (so a rule using
# it would change meaning from one machine to the next), ``posixrules`` is a
# template for POSIX TZ strings and ``Factory`` is the "zone not configured"
# placeholder (abbreviation ``-00``).
_NOT_IANA_ZONES = frozenset({"localtime", "posixrules", "Factory"})


def zone(tz: str) -> ZoneInfo:
    """The IANA time zone ``tz``; ``ValueError`` if it does not exist.

    Host-dependent pseudo-zones such as ``localtime`` are rejected: every rule
    must mean the same thing on every machine.
    """
    if not isinstance(tz, str) or not tz.strip():
        raise ValueError(f"time zone must be a non-empty IANA name, got {tz!r}")
    if tz in _NOT_IANA_ZONES:
        raise ValueError(
            f"{tz!r} is not an IANA time zone (it depends on the host or is a placeholder); "
            "name the zone explicitly, e.g. 'America/New_York' or 'UTC'"
        )
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown IANA time zone {tz!r} (e.g. 'America/New_York')") from exc


def _resolve_zone(tz: "str | ZoneInfo") -> ZoneInfo:
    return tz if isinstance(tz, ZoneInfo) else zone(tz)


def _wall_to_utc(local: datetime, tz: ZoneInfo) -> datetime:
    # PEP 495: with fold=0 a time in the gap uses the offset from *before* the
    # transition, which lands exactly "gap" later on the new offset (02:30 EST
    # → 07:30 UTC = 03:30 EDT); an ambiguous time takes its first occurrence.
    return local.replace(tzinfo=tz, fold=0).astimezone(UTC)


def to_utc(local: datetime, tz: "str | ZoneInfo") -> datetime:
    """Interpret a naive local wall-clock time in IANA zone ``tz`` as a UTC instant.

    * Nonexistent times (spring-forward gap) shift **forward** by the gap:
      02:30 on 2026-03-08 in New York → 03:30 EDT (07:30 UTC).
    * Ambiguous times (fall-back) resolve to the **first** occurrence:
      01:30 on 2026-11-01 in New York → 01:30 EDT (05:30 UTC). The input's
      ``fold`` attribute is ignored.
    """
    raw: object = local  # checked at run time: a date or a string has no wall-clock time
    if not isinstance(raw, datetime):
        raise TypeError(f"to_utc expects a naive local datetime, got {raw!r}")
    if local.tzinfo is not None:
        raise ValueError(
            f"to_utc expects a naive local wall-clock time, got aware {local.isoformat()}"
        )
    return _wall_to_utc(local, _resolve_zone(tz))


def to_local(ts: datetime, tz: "str | ZoneInfo") -> datetime:
    """The aware local time of UTC instant ``ts`` in zone ``tz``."""
    return ensure_utc(ts).astimezone(_resolve_zone(tz))


# ── value parsing / formatting for documents ─────────────────────────────────
def parse_time(value: object, where: str = "time") -> time:
    """``"HH:MM"`` or ``"HH:MM:SS"`` (or a naive :class:`datetime.time`)."""
    if isinstance(value, time):
        _validate_wall_time(value, where)
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        raise ValueError(
            f"{where}: time must be a quoted 'HH:MM' string, got the number {value} "
            "(YAML reads unquoted values like 17:00 as base-60 numbers)"
        )
    if isinstance(value, str) and (match := _TIME_TEXT.fullmatch(value.strip())):
        hour, minute, second = int(match[1]), int(match[2]), int(match[3] or 0)
        if hour > 23 or minute > 59 or second > 59:
            raise ValueError(f"{where}: invalid time {value!r} (00:00 … 23:59)")
        return time(hour, minute, second)
    raise ValueError(f"{where}: invalid time {value!r}; expected 'HH:MM'")


def format_time(value: time) -> str:
    if value.second:
        return f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    return f"{value.hour:02d}:{value.minute:02d}"


def parse_date(value: object, where: str = "date") -> date:
    """``"YYYY-MM-DD"`` (or a :class:`datetime.date`, which YAML produces for unquoted dates)."""
    if isinstance(value, datetime):
        raise ValueError(f"{where}: expected a date, got a datetime {value!r}")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE_TEXT.fullmatch(value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{where}: invalid date {value!r}") from exc
    raise ValueError(f"{where}: invalid date {value!r}; expected 'YYYY-MM-DD'")


def _validate_wall_time(value: object, where: str) -> None:
    if not isinstance(value, time):
        raise ValueError(
            f"{where}: expected a local wall-clock datetime.time, got {value!r} "
            "(use parse_time for 'HH:MM' text)"
        )
    if value.tzinfo is not None:
        raise ValueError(f"{where}: local wall-clock times carry no tzinfo, got {value!r}")
    if value.microsecond:
        raise ValueError(f"{where}: sub-second times are not supported, got {value!r}")


def _validate_date(value: object, where: str) -> None:
    """Configuration dates must be plain :class:`datetime.date` objects."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"{where}: expected a datetime.date, got {value!r}")


def _require_date(value: object, method: str, instead: str) -> None:
    """Guard for methods taking a *local date*.

    A :class:`datetime` is a :class:`date` subclass, so it would be accepted
    silently and its own (typically UTC) date used, which is the wrong local
    day around midnight. Refuse it and point at the instant-based method.
    """
    if isinstance(value, datetime):
        raise TypeError(
            f"{method} takes a local calendar date, got the datetime {value.isoformat()}; "
            f"use {instead} for an instant"
        )
    if not isinstance(value, date):
        raise TypeError(f"{method} takes a datetime.date, got {value!r}")


def _validate_id(value: object, kind: str) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"invalid {kind} id {value!r}: use lower_snake_case "
            "(a letter, then letters, digits or '_', 2-64 characters)"
        )


def _check_keys(
    data: Mapping[str, Any], *, required: set[str], optional: set[str], where: str
) -> None:
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"{where}: missing required key(s) {', '.join(missing)}")
    unknown = sorted(set(data) - required - optional)
    if unknown:
        allowed = ", ".join(sorted(required | optional))
        raise ValueError(f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {allowed})")


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _sequence(value: object, where: str) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{where}: expected a list, got {type(value).__name__}")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{where}: expected a string, got {value!r}")
    return value


def _optional_text(data: Mapping[str, Any], key: str, default: str, where: str) -> str:
    """``data[key]`` as a string; ``default`` only when the key is missing or null.

    (``data.get(key) or default`` would silently turn ``false`` or ``0`` into
    the default instead of reporting the type error.)
    """
    value = data.get(key)
    return default if value is None else _text(value, f"{where}.{key}")


def _flag(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{where}: expected true or false, got {value!r}")
    return value


# ── span helpers (half-open [start, end) intervals) ──────────────────────────
Span = tuple[datetime, datetime]


def _merge(spans: Iterable[Span]) -> list[Span]:
    """Sort and merge overlapping or touching spans; drop empty ones."""
    merged: list[Span] = []
    for start, end in sorted(span for span in spans if span[1] > span[0]):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _subtract(spans: list[Span], holes: list[Span]) -> list[Span]:
    """``spans`` minus ``holes``; both sorted and merged."""
    result: list[Span] = []
    index = 0
    for start, end in spans:
        cursor = start
        while index < len(holes) and holes[index][1] <= cursor:
            index += 1
        probe = index
        while probe < len(holes) and holes[probe][0] < end:
            hole_start, hole_end = holes[probe]
            if hole_start > cursor:
                result.append((cursor, hole_start))
            cursor = max(cursor, hole_end)
            if cursor >= end:
                break
            probe += 1
        if cursor < end:
            result.append((cursor, end))
    return result


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


# ── weekly intervals ─────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class WeeklyInterval:
    """One recurring open period in local wall-clock time, e.g. ``SUN 17:00 - MON 16:00``.

    The close may be on a later weekday, or earlier in the week (the interval
    then wraps over the week end: ``FRI 22:00 - MON 01:00``). An interval
    whose close equals its open is rejected (use ``always_open``).
    """

    open_day: Weekday
    open_time: time
    close_day: Weekday
    close_time: time

    def __post_init__(self) -> None:
        object.__setattr__(self, "open_day", Weekday.parse(self.open_day))
        object.__setattr__(self, "close_day", Weekday.parse(self.close_day))
        # Types first: the readable name below formats both times.
        _validate_wall_time(self.open_time, f"weekly interval opening {self.open_day.name}")
        _validate_wall_time(self.close_time, f"weekly interval closing {self.close_day.name}")
        if self.open_offset == self.close_offset:
            raise ValueError(
                f"weekly interval {self} has no length; use always_open for a 24/7 market"
            )

    @classmethod
    def parse(cls, text: str) -> "WeeklyInterval":
        """Parse ``"SUN 17:00 - MON 16:00"`` (the inverse of ``str()``)."""
        match = _INTERVAL_TEXT.fullmatch(text) if isinstance(text, str) else None
        if match is None:
            raise ValueError(
                f"invalid weekly interval {text!r}; expected 'DAY HH:MM - DAY HH:MM', "
                "e.g. 'SUN 17:00 - MON 16:00'"
            )
        where = f"weekly interval {text!r}"
        return cls(
            open_day=Weekday.parse(match[1]),
            open_time=parse_time(match[2], where),
            close_day=Weekday.parse(match[3]),
            close_time=parse_time(match[4], where),
        )

    def __str__(self) -> str:
        return (
            f"{self.open_day.name} {format_time(self.open_time)} - "
            f"{self.close_day.name} {format_time(self.close_time)}"
        )

    @property
    def open_offset(self) -> timedelta:
        """Wall-clock offset of the open from Monday 00:00."""
        return _week_offset(self.open_day, self.open_time)

    @property
    def close_offset(self) -> timedelta:
        return _week_offset(self.close_day, self.close_time)

    @property
    def duration(self) -> timedelta:
        """Wall-clock length (the real length differs by the DST shift on change weekends)."""
        return (self.close_offset - self.open_offset) % _WEEK


def _week_offset(day: Weekday, at: time) -> timedelta:
    return timedelta(days=int(day), hours=at.hour, minutes=at.minute, seconds=at.second)


def _merge_weekly(
    intervals: Sequence[WeeklyInterval], where: str
) -> tuple[tuple[timedelta, timedelta], ...]:
    """Merge weekly intervals on the cyclic week into ``(start, end)`` offsets from
    Monday 00:00, sorted by start; ``end`` may exceed one week (wrapping spans)."""
    merged: list[list[timedelta]] = []
    for start, end in sorted((iv.open_offset, iv.open_offset + iv.duration) for iv in intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    while len(merged) > 1 and merged[-1][1] - _WEEK >= merged[0][0]:
        first = merged.pop(0)
        merged[-1][1] = max(merged[-1][1], first[1] + _WEEK)
    if sum((end - start for start, end in merged), timedelta()) >= _WEEK:
        raise ValueError(f"{where}: weekly intervals cover the whole week; use always_open: true")
    return tuple((start, end) for start, end in merged)


# ── trading calendars ────────────────────────────────────────────────────────
class HolidayRule(StrEnum):
    """How a holiday date closes a calendar (see the module docstring)."""

    CALENDAR_DATE = "calendar_date"
    TRADE_DATE = "trade_date"


def _session_opens(sessions: Sequence[tuple[timedelta, timedelta]]) -> tuple[timedelta, ...]:
    """Week offsets at which a session opens: the open of a configured interval
    that no *other* interval already covers.

    Touching intervals (``... - MON 17:00``, ``MON 17:00 - ...``) are separate
    sessions, so the second one's open counts; an interval opening strictly
    inside another one does not, because the market is already open then.
    """
    opens = {
        start
        for start, _ in sessions
        if not any(
            other_start < at < other_end
            for other_start, other_end in sessions
            for at in (start, start + _WEEK)
        )
    }
    return tuple(sorted(opens))


def _trade_date(close_local: datetime) -> date:
    """The local date a session belongs to: its close date.

    A session closing at 00:00 belongs to the day before.
    """
    if close_local.time() == _MIDNIGHT:
        return close_local.date() - _DAY
    return close_local.date()


@dataclass(frozen=True, slots=True)
class TradingCalendar:
    """When a market is open. All inputs and outputs are UTC-aware instants.

    Each configured weekly interval is a *session* (holidays and early closes
    act on sessions, see the module docstring). Open periods are reported
    half-open ``[open, close)`` with adjacent or overlapping sessions merged,
    so an interval returned by the queries is the maximal open period.
    """

    id: str
    timezone: str
    intervals: tuple[WeeklyInterval, ...] = ()
    always_open: bool = False
    holidays: frozenset[date] = frozenset()
    early_closes: tuple[tuple[date, time], ...] = ()
    description: str = ""
    holiday_rule: HolidayRule = HolidayRule.CALENDAR_DATE

    _tz: ZoneInfo = field(init=False, repr=False, compare=False)
    # (open, close) week offsets of every configured interval, *not* merged.
    _sessions: tuple[tuple[timedelta, timedelta], ...] = field(
        init=False, repr=False, compare=False
    )
    _opens: tuple[timedelta, ...] = field(init=False, repr=False, compare=False)
    _early_by_date: dict[date, time] = field(init=False, repr=False, compare=False)
    _week_cache: dict[date, tuple[Span, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_id(self.id, "trading calendar")
        where = f"trading calendar {self.id!r}"
        object.__setattr__(self, "_tz", zone(self.timezone))
        object.__setattr__(self, "intervals", self._normalise_intervals(where))
        _flag(self.always_open, f"{where}: always_open")
        _text(self.description, f"{where}: description")
        object.__setattr__(self, "holidays", frozenset(self.holidays))
        for day in self.holidays:
            _validate_date(day, f"{where}: holiday")
        try:
            object.__setattr__(self, "holiday_rule", HolidayRule(self.holiday_rule))
        except ValueError as exc:
            choices = ", ".join(rule.value for rule in HolidayRule)
            raise ValueError(
                f"{where}: holiday_rule must be one of {choices}, got {self.holiday_rule!r}"
            ) from exc
        by_date = self._normalise_early_closes(where)
        object.__setattr__(self, "early_closes", tuple(sorted(by_date.items())))
        object.__setattr__(self, "_early_by_date", by_date)
        object.__setattr__(self, "_week_cache", {})
        both = sorted(self.holidays & by_date.keys())
        if both:
            listed = ", ".join(day.isoformat() for day in both)
            raise ValueError(f"{where}: {listed} is both a holiday and an early close")
        if self.always_open:
            if self.intervals or self.holidays or self.early_closes:
                raise ValueError(
                    f"{where}: an always_open calendar cannot also have weekly intervals, "
                    "holidays or early closes"
                )
            object.__setattr__(self, "_sessions", ())
            object.__setattr__(self, "_opens", ())
            return
        if not self.intervals:
            raise ValueError(f"{where}: no weekly intervals; add some or set always_open: true")
        _merge_weekly(self.intervals, where)  # rejects a schedule that covers the whole week
        sessions = tuple((iv.open_offset, iv.open_offset + iv.duration) for iv in self.intervals)
        object.__setattr__(self, "_sessions", sessions)
        object.__setattr__(self, "_opens", _session_opens(sessions))
        self._validate_exceptions(where)

    def _normalise_intervals(self, where: str) -> tuple[WeeklyInterval, ...]:
        raw: object = self.intervals  # validated at run time: it may come from untyped code
        if isinstance(raw, str) or not isinstance(raw, Iterable):
            raise ValueError(f"{where}: intervals must be a list of weekly intervals, got {raw!r}")
        normalised: list[WeeklyInterval] = []
        for item in raw:
            if isinstance(item, str):
                normalised.append(WeeklyInterval.parse(item))
            elif isinstance(item, WeeklyInterval):
                normalised.append(item)
            else:
                raise ValueError(
                    f"{where}: intervals must be WeeklyInterval values or "
                    f"'DAY HH:MM - DAY HH:MM' strings, got {item!r}"
                )
        return tuple(normalised)

    def _normalise_early_closes(self, where: str) -> dict[date, time]:
        raw: Iterable[object] = self.early_closes
        if isinstance(self.early_closes, Mapping):
            raw = self.early_closes.items()
        by_date: dict[date, time] = {}
        for entry in raw:
            if not isinstance(entry, tuple | list) or len(entry) != 2:
                raise ValueError(f"{where}: early closes must be (date, time) pairs, got {entry!r}")
            day, at = entry
            _validate_date(day, f"{where}: early-close date")
            _validate_wall_time(at, f"{where}: early close on {day.isoformat()}")
            if day in by_date:
                raise ValueError(
                    f"{where}: an early-close date is listed more than once ({day.isoformat()})"
                )
            by_date[day] = at
        return by_date

    def _validate_exceptions(self, where: str) -> None:
        """Reject holidays and early closes that would silently change nothing.

        A trade-date holiday must fall on a weekday on which some session
        closes; an early close must fall inside a scheduled session that a
        trade-date holiday has not already cancelled. Either mistake usually
        means a wrong date in the yearly holiday list.
        """
        trade_date_rule = self.holiday_rule is HolidayRule.TRADE_DATE
        if trade_date_rule:
            reference = datetime.combine(_monday(date(2026, 1, 5)), _MIDNIGHT)
            closing_days = {
                Weekday.of(_trade_date(reference + close)) for _, close in self._sessions
            }
            for day in sorted(self.holidays):
                if Weekday.of(day) not in closing_days:
                    names = ", ".join(str(d) for d in week_order(closing_days))
                    raise ValueError(
                        f"{where}: holiday {day.isoformat()} is a {Weekday.of(day)}, but with "
                        f"holiday_rule trade_date a holiday cancels the sessions that close on "
                        f"it and sessions only close on {names}; it would close nothing"
                    )
        for day, at in self.early_closes:
            label = f"early close {day.isoformat()} ({Weekday.of(day)}) {format_time(at)}"
            containing = self._sessions_containing(datetime.combine(day, at))
            if not containing:
                raise ValueError(
                    f"{where}: {label} is outside the weekly schedule, so it would close "
                    "nothing; check the date and time"
                )
            trade_dates = sorted({_trade_date(close) for _, close in containing})
            if trade_date_rule and all(day in self.holidays for day in trade_dates):
                raise ValueError(
                    f"{where}: {label} falls in a session already cancelled by the holiday "
                    f"{', '.join(day.isoformat() for day in trade_dates)}, so it would close "
                    "nothing"
                )

    def _sessions_containing(self, local: datetime) -> list[tuple[datetime, datetime]]:
        """Scheduled (wall-clock) session occurrences with ``open <= local < close``."""
        monday = datetime.combine(_monday(local.date()), _MIDNIGHT)
        found: list[tuple[datetime, datetime]] = []
        for start, end in self._sessions:
            for week in (monday - _WEEK, monday):  # an occurrence starts < 1 week before
                open_local, close_local = week + start, week + end
                if open_local <= local < close_local:
                    found.append((open_local, close_local))
        return found

    # ── queries ─────────────────────────────────────────────────────────────
    def is_holiday(self, day: date) -> bool:
        _require_date(day, "is_holiday", "is_open(ts)")
        return day in self.holidays

    def early_close_on(self, day: date) -> time | None:
        _require_date(day, "early_close_on", "is_open(ts)")
        return self._early_by_date.get(day)

    def is_open(self, ts: datetime) -> bool:
        if self.always_open:
            ensure_utc(ts)
            return True
        return self.current_interval(ts) is not None

    def current_interval(self, ts: datetime) -> Span | None:
        """The full (unclipped) open interval containing ``ts``, or ``None`` if closed.

        An ``always_open`` calendar reports ``(UNBOUNDED_START, UNBOUNDED_END)``.
        """
        ts = ensure_utc(ts)
        if self.always_open:
            return (UNBOUNDED_START, UNBOUNDED_END)
        for start, end in self._week_spans(_monday(ts.astimezone(self._tz).date())):
            if start <= ts < end:
                return (start, end)
        return None

    def open_intervals(self, start: datetime, end: datetime) -> list[Span]:
        """Open periods within ``[start, end)``, clipped to it, merged, in order (UTC)."""
        start, end = ensure_utc(start), ensure_utc(end)
        if end < start:
            raise ValueError(f"end {end.isoformat()} is before start {start.isoformat()}")
        if end == start:
            return []
        if self.always_open:
            return [(start, end)]
        return [(max(s, start), min(e, end)) for s, e in self._spans_around(start, end)]

    def next_open(self, ts: datetime) -> datetime | None:
        """The earliest instant ``>= ts`` at which the market is open.

        That is ``ts`` itself when the market is open at ``ts``; otherwise the
        next opening. ``None`` only if the market never opens again.
        """
        ts = ensure_utc(ts)
        if self.always_open:
            return ts
        span = self._first_span_ending_after(ts)
        return None if span is None else max(span[0], ts)

    def next_close(self, ts: datetime) -> datetime | None:
        """The end of the open interval containing ``ts`` or, if closed at ``ts``,
        of the next one. ``None`` for an ``always_open`` calendar."""
        ts = ensure_utc(ts)
        if self.always_open:
            return None
        span = self._first_span_ending_after(ts)
        return None if span is None else span[1]

    # ── internals ───────────────────────────────────────────────────────────
    def _first_span_ending_after(self, ts: datetime) -> Span | None:
        week = _monday(ts.astimezone(self._tz).date())
        last_exception = max([*self.holidays, *self._early_by_date.keys()], default=week)
        horizon = max(week, _monday(last_exception)) + 3 * _WEEK
        while week <= horizon:
            for span in self._week_spans(week):
                if span[1] > ts:
                    return span
            week += _WEEK
        return None  # pragma: no cover - unreachable while weekly intervals exist

    def _week_spans(self, week: date) -> tuple[Span, ...]:
        """Complete merged open spans touching the local week starting Monday ``week``.

        Memoised: the calendar is immutable, and the paper simulator and the
        lab ask ``is_open`` for every bar of every instrument.
        """
        cached = self._week_cache.get(week)
        if cached is None:
            lo = _wall_to_utc(datetime.combine(week - _DAY, _MIDNIGHT), self._tz)
            hi = _wall_to_utc(datetime.combine(week + _WEEK + _DAY, _MIDNIGHT), self._tz)
            cached = tuple(self._spans_around(lo, hi))
            if len(self._week_cache) >= _WEEK_CACHE_SIZE:
                self._week_cache.clear()
            self._week_cache[week] = cached
        return cached

    def _next_scheduled_open(self, after_local: datetime) -> datetime:
        """The next session open (see :func:`_session_opens`) strictly after ``after_local``."""
        week = datetime.combine(_monday(after_local.date()) - _WEEK, _MIDNIGHT)
        candidates = (week + offset * _WEEK + start for offset in range(4) for start in self._opens)
        return min(candidate for candidate in candidates if candidate > after_local)

    def _spans_around(self, lo: datetime, hi: datetime) -> list[Span]:
        """Merged open spans (UTC) intersecting ``[lo, hi)``, *unclipped*.

        Occurrences are generated with a two-week margin on both sides; a
        merged span is always shorter than a week (whole-week schedules are
        rejected), so every span intersecting the range is complete.
        """
        tz = self._tz
        first_week = _monday(lo.astimezone(tz).date()) - 2 * _WEEK
        last_week = _monday(hi.astimezone(tz).date()) + 2 * _WEEK
        trade_date_rule = self.holiday_rule is HolidayRule.TRADE_DATE

        occurrences: list[Span] = []
        week = first_week
        while week <= last_week:
            base = datetime.combine(week, _MIDNIGHT)
            for start, end in self._sessions:  # per session: holidays cancel sessions
                open_local, close_local = base + start, base + end
                if trade_date_rule and _trade_date(close_local) in self.holidays:
                    continue
                occurrences.append((_wall_to_utc(open_local, tz), _wall_to_utc(close_local, tz)))
            week += _WEEK

        closed: list[Span] = []
        window_first, window_last = first_week - _WEEK, last_week + 2 * _WEEK
        if not trade_date_rule:
            closed.extend(
                (
                    _wall_to_utc(datetime.combine(day, _MIDNIGHT), tz),
                    _wall_to_utc(datetime.combine(day + _DAY, _MIDNIGHT), tz),
                )
                for day in self.holidays
                if window_first <= day <= window_last
            )
        for day, at in self.early_closes:
            if window_first <= day <= window_last:
                close_local = datetime.combine(day, at)
                reopen_local = self._next_scheduled_open(close_local)
                closed.append((_wall_to_utc(close_local, tz), _wall_to_utc(reopen_local, tz)))

        spans = _subtract(_merge(occurrences), _merge(closed))
        lo_utc, hi_utc = ensure_utc(lo), ensure_utc(hi)
        return [(s, e) for s, e in spans if e > lo_utc and s < hi_utc]

    # ── serialization ───────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        data = _mapping(data, "trading calendar")
        where = f"trading calendar {data.get('id')!r}"
        _check_keys(
            data,
            required={"id", "timezone"},
            optional={
                "always_open",
                "weekly",
                "holiday_rule",
                "holidays",
                "early_closes",
                "description",
            },
            where=where,
        )
        holidays: list[date] = []
        for raw in _sequence(data.get("holidays"), f"{where}.holidays"):
            day = parse_date(raw, f"{where}.holidays")
            if day in holidays:
                raise ValueError(f"{where}: holiday {day.isoformat()} is listed twice")
            holidays.append(day)
        early_raw = data.get("early_closes")
        if early_raw is None or early_raw == []:  # `early_closes: []` reads naturally too
            early_raw = {}
        early: dict[date, time] = {}
        for raw_day, raw_time in _mapping(early_raw, f"{where}.early_closes").items():
            day = parse_date(raw_day, f"{where}.early_closes")
            if day in early:
                raise ValueError(f"{where}: early close {day.isoformat()} is listed twice")
            early[day] = parse_time(raw_time, f"{where}.early_closes[{day.isoformat()}]")
        rule_raw = data.get("holiday_rule", HolidayRule.CALENDAR_DATE.value)
        try:
            rule = HolidayRule(_text(rule_raw, f"{where}.holiday_rule"))
        except ValueError as exc:
            choices = ", ".join(r.value for r in HolidayRule)
            raise ValueError(
                f"{where}: holiday_rule must be one of {choices}, got {rule_raw!r}"
            ) from exc
        return cls(
            id=_text(data["id"], f"{where}.id"),
            timezone=_text(data["timezone"], f"{where}.timezone"),
            intervals=tuple(
                WeeklyInterval.parse(_text(raw, f"{where}.weekly"))
                for raw in _sequence(data.get("weekly"), f"{where}.weekly")
            ),
            always_open=_flag(data.get("always_open", False), f"{where}.always_open"),
            holidays=frozenset(holidays),
            early_closes=tuple(early.items()),
            description=_optional_text(data, "description", "", where),
            holiday_rule=rule,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timezone": self.timezone,
            "always_open": self.always_open,
            "weekly": [str(interval) for interval in self.intervals],
            "holiday_rule": self.holiday_rule.value,
            "holidays": [day.isoformat() for day in sorted(self.holidays)],
            "early_closes": {day.isoformat(): format_time(at) for day, at in self.early_closes},
            "description": self.description,
        }


# ── trading-day rules ────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class TradingDayRule:
    """Which trading day an instant belongs to.

    With ``rollover`` 17:00 America/New_York (``ny_1700``) trading day *D*
    runs from 17:00 New York on *D − 1* to 17:00 New York on *D*: Sunday
    18:00 New York already belongs to Monday. With a 00:00 rollover the
    trading day is the local calendar date. Trading days are a strict
    partition of time: across DST changes a day lasts 23 or 25 hours. The rule
    does not skip weekends or holidays (that is the calendar's job).
    """

    id: str
    timezone: str
    rollover: time
    description: str = ""

    _tz: ZoneInfo = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_id(self.id, "trading-day rule")
        object.__setattr__(self, "_tz", zone(self.timezone))
        _validate_wall_time(self.rollover, f"trading-day rule {self.id!r}: rollover")
        _text(self.description, f"trading-day rule {self.id!r}: description")

    def trading_day(self, ts: datetime) -> date:
        ts = ensure_utc(ts)
        local = ts.astimezone(self._tz)
        day = local.date()
        if self.rollover != _MIDNIGHT and local.time() >= self.rollover:
            day += _DAY
        # Wall-clock comparison is ambiguous inside a fall-back hour or a gap;
        # day_bounds is the authority, so settle the edge cases against it.
        start, end = self.day_bounds(day)
        if ts < start:
            return day - _DAY
        if ts >= end:
            return day + _DAY
        return day

    def day_bounds(self, day: date) -> Span:
        """UTC ``[start, end)`` of trading day ``day``."""
        _require_date(day, "day_bounds", "trading_day(ts)")
        if self.rollover == _MIDNIGHT:
            start_local = datetime.combine(day, _MIDNIGHT)
        else:
            start_local = datetime.combine(day - _DAY, self.rollover)
        return (
            _wall_to_utc(start_local, self._tz),
            _wall_to_utc(start_local + _DAY, self._tz),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        data = _mapping(data, "trading-day rule")
        where = f"trading-day rule {data.get('id')!r}"
        _check_keys(
            data,
            required={"id", "timezone", "rollover"},
            optional={"description"},
            where=where,
        )
        return cls(
            id=_text(data["id"], f"{where}.id"),
            timezone=_text(data["timezone"], f"{where}.timezone"),
            rollover=parse_time(data["rollover"], f"{where}.rollover"),
            description=_optional_text(data, "description", "", where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timezone": self.timezone,
            "rollover": format_time(self.rollover),
            "description": self.description,
        }


# ── session windows ──────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class SessionWindow:
    """A named daily window in local time, e.g. ``ny_orb_15`` 09:30–09:45 New York.

    ``days`` are the *local* weekdays on which the window **starts**. A window
    whose ``end`` is not after its ``start`` crosses local midnight (equal
    times make a 24-hour window). Windows ignore holidays; combine them with a
    :class:`TradingCalendar` when that matters.
    """

    id: str
    name: str
    timezone: str
    start: time
    end: time
    days: frozenset[Weekday]
    description: str = ""

    _tz: ZoneInfo = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_id(self.id, "session window")
        where = f"session window {self.id!r}"
        object.__setattr__(self, "_tz", zone(self.timezone))
        try:
            days = parse_weekdays(self.days)  # a set, a list or a range like "MON-FRI"
        except ValueError as exc:
            raise ValueError(f"{where}: days: {exc}") from exc
        object.__setattr__(self, "days", days)
        if not self.days:
            raise ValueError(f"{where}: needs at least one weekday")
        _validate_wall_time(self.start, f"{where}: start")
        _validate_wall_time(self.end, f"{where}: end")
        # A blank name would not survive a round trip: from_dict reads a missing
        # name as the id.
        if not _text(self.name, f"{where}: name").strip():
            raise ValueError(f"{where}: name must not be blank (omit it to use the id)")
        _text(self.description, f"{where}: description")

    @property
    def crosses_midnight(self) -> bool:
        return self.end <= self.start

    def window_on(self, day: date) -> Span | None:
        """UTC bounds of the window that starts on local date ``day``.

        ``None`` if the window does not run on that weekday, or if shifting
        nonexistent times forward leaves it empty (e.g. 02:30-03:00 on a
        spring-forward night).
        """
        _require_date(day, "window_on", "window_at(ts)")
        if Weekday.of(day) not in self.days:
            return None
        end_day = day + _DAY if self.crosses_midnight else day
        start = _wall_to_utc(datetime.combine(day, self.start), self._tz)
        end = _wall_to_utc(datetime.combine(end_day, self.end), self._tz)
        return (start, end) if end > start else None

    def window_at(self, ts: datetime) -> Span | None:
        """The window containing ``ts`` (one that started the previous local day included)."""
        ts = ensure_utc(ts)
        local_day = ts.astimezone(self._tz).date()
        for day in (local_day - _DAY, local_day):
            window = self.window_on(day)
            if window is not None and window[0] <= ts < window[1]:
                return window
        return None

    def contains(self, ts: datetime) -> bool:
        return self.window_at(ts) is not None

    def windows_between(self, start: datetime, end: datetime) -> list[Span]:
        """All windows overlapping ``[start, end)``, unclipped, in chronological order.

        An empty range (``start == end``) overlaps nothing, as in
        :meth:`TradingCalendar.open_intervals`; use :meth:`window_at` for an instant.
        """
        start, end = ensure_utc(start), ensure_utc(end)
        if end < start:
            raise ValueError(f"end {end.isoformat()} is before start {start.isoformat()}")
        if end == start:
            return []
        day = start.astimezone(self._tz).date() - _DAY
        last = end.astimezone(self._tz).date()
        windows: list[Span] = []
        while day <= last:
            window = self.window_on(day)
            if window is not None and window[1] > start and window[0] < end:
                windows.append(window)
            day += _DAY
        return windows

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        data = _mapping(data, "session window")
        where = f"session window {data.get('id')!r}"
        _check_keys(
            data,
            required={"id", "timezone", "start", "end", "days"},
            optional={"name", "description"},
            where=where,
        )
        window_id = _text(data["id"], f"{where}.id")
        try:
            days = parse_weekdays(data["days"])
        except ValueError as exc:
            raise ValueError(f"{where}.days: {exc}") from exc
        return cls(
            id=window_id,
            name=_optional_text(data, "name", window_id, where),
            timezone=_text(data["timezone"], f"{where}.timezone"),
            start=parse_time(data["start"], f"{where}.start"),
            end=parse_time(data["end"], f"{where}.end"),
            days=days,
            description=_optional_text(data, "description", "", where),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "timezone": self.timezone,
            "start": format_time(self.start),
            "end": format_time(self.end),
            "days": [day.name for day in week_order(self.days)],
            "description": self.description,
        }


# ── the book ─────────────────────────────────────────────────────────────────
def _index[T: (TradingCalendar, TradingDayRule, SessionWindow)](
    items: Iterable[T], kind: str
) -> dict[str, T]:
    indexed: dict[str, T] = {}
    for item in items:
        if item.id in indexed:
            raise ValueError(f"duplicate {kind} id {item.id!r}")
        indexed[item.id] = item
    return indexed


def _lookup[T](items: Mapping[str, T], key: str, kind: str) -> T:
    try:
        return items[key]
    except KeyError:
        available = ", ".join(sorted(items)) or "none configured"
        raise KeyError(f"unknown {kind} {key!r}; available: {available}") from None


class SessionBook:
    """All configured calendars, trading-day rules and session windows.

    ``classification`` is an ordered list of window ids: :meth:`classify`
    labels an instant with the first window that contains it (``off_hours``
    when none does), so each trade gets exactly one session label for
    analytics. Configuration order is preserved for :meth:`to_document`.
    """

    def __init__(
        self,
        *,
        calendars: Iterable[TradingCalendar] = (),
        trading_day_rules: Iterable[TradingDayRule] = (),
        windows: Iterable[SessionWindow] = (),
        classification: Sequence[str] = (),
    ) -> None:
        self._calendars = _index(calendars, "trading calendar")
        self._rules = _index(trading_day_rules, "trading-day rule")
        self._windows = _index(windows, "session window")
        if isinstance(classification, str):
            raise ValueError(
                "session_classification must be a list of session window ids, "
                f"not the string {classification!r}"
            )
        # Order is the whole point (the first containing window wins). A set has
        # no order, and string hashing is salted per process, so the same book
        # would classify overlapping windows differently from run to run.
        if isinstance(classification, AbstractSet | Mapping):
            raise ValueError(
                "session_classification must be an ordered list of session window ids, "
                f"got the unordered {type(classification).__name__} {classification!r}"
            )
        self._classification = tuple(classification)
        seen: set[str] = set()
        for window_id in self._classification:
            _text(window_id, "session_classification entry")
            if window_id in seen:
                raise ValueError(f"session_classification lists {window_id!r} twice")
            seen.add(window_id)
            if window_id not in self._windows:
                available = ", ".join(sorted(self._windows)) or "none configured"
                raise ValueError(
                    f"session_classification refers to unknown session window {window_id!r}; "
                    f"available: {available}"
                )

    # ── lookup ──────────────────────────────────────────────────────────────
    @property
    def calendars(self) -> tuple[TradingCalendar, ...]:
        return tuple(self._calendars.values())

    @property
    def trading_day_rules(self) -> tuple[TradingDayRule, ...]:
        return tuple(self._rules.values())

    @property
    def windows(self) -> tuple[SessionWindow, ...]:
        return tuple(self._windows.values())

    @property
    def classification(self) -> tuple[str, ...]:
        return self._classification

    def calendar(self, calendar_id: str) -> TradingCalendar:
        return _lookup(self._calendars, calendar_id, "trading calendar")

    def trading_day_rule(self, rule_id: str) -> TradingDayRule:
        return _lookup(self._rules, rule_id, "trading-day rule")

    def window(self, window_id: str) -> SessionWindow:
        return _lookup(self._windows, window_id, "session window")

    # ── labelling ───────────────────────────────────────────────────────────
    def classify(self, ts: datetime) -> str:
        """The first classification window containing ``ts``, else ``off_hours``."""
        ts = ensure_utc(ts)
        for window_id in self._classification:
            if self._windows[window_id].contains(ts):
                return window_id
        return OFF_HOURS

    def labels(self, ts: datetime) -> frozenset[str]:
        """Ids of *all* windows containing ``ts`` (e.g. ``{"new_york", "ny_orb_15", …}``)."""
        ts = ensure_utc(ts)
        return frozenset(wid for wid, window in self._windows.items() if window.contains(ts))

    # ── documents ───────────────────────────────────────────────────────────
    @classmethod
    def from_document(cls, doc: Mapping[str, Any]) -> "SessionBook":
        """Build from a configuration document (``config/catalog/sessions.yaml``).

        Reads ``trading_day_rules``, ``calendars``, ``session_windows`` and
        ``session_classification``; other top-level keys are ignored so the
        sessions may live inside a larger catalog document.
        """
        doc = _mapping(doc, "session document")

        def entries(key: str) -> list[Mapping[str, Any]]:
            return [
                _mapping(entry, f"{key}[{position}]")
                for position, entry in enumerate(_sequence(doc.get(key), key))
            ]

        classification = [
            _text(entry, f"session_classification[{position}]")
            for position, entry in enumerate(
                _sequence(doc.get("session_classification"), "session_classification")
            )
        ]
        return cls(
            trading_day_rules=[TradingDayRule.from_dict(e) for e in entries("trading_day_rules")],
            calendars=[TradingCalendar.from_dict(e) for e in entries("calendars")],
            windows=[SessionWindow.from_dict(e) for e in entries("session_windows")],
            classification=classification,
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "trading_day_rules": [rule.to_dict() for rule in self._rules.values()],
            "calendars": [calendar.to_dict() for calendar in self._calendars.values()],
            "session_windows": [window.to_dict() for window in self._windows.values()],
            "session_classification": list(self._classification),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SessionBook):
            return NotImplemented
        return (
            self.calendars == other.calendars
            and self.trading_day_rules == other.trading_day_rules
            and self.windows == other.windows
            and self.classification == other.classification
        )

    def __repr__(self) -> str:
        return (
            f"SessionBook(calendars={list(self._calendars)}, "
            f"trading_day_rules={list(self._rules)}, windows={list(self._windows)}, "
            f"classification={list(self._classification)})"
        )

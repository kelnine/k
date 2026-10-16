"""Pine-style session strings as strategy parameters (``"2000-0200:1234567"``).

Pine scripts take their windows as ``input.session`` strings and test bars with
``not na(time(timeframe.period, sess, "America/New_York"))``. Ports keep those
strings as parameters (``Params`` are part of the version), and this module
evaluates them with the same meaning, DST-correct:

* **Format** — ``HHMM-HHMM`` with an optional ``:days`` mask of the digits 1–7,
  numbered like Pine (1 = Sunday, 2 = Monday … 7 = Saturday). Several ranges are
  separated by commas, and a mask applies to the ranges before it that have none:
  ``"0900-1600,1700-2000:23456"``. Without a mask a range runs on every day
  (Pine v5+ default ``1234567``). ``"24x7"`` is ``"0000-0000:1234567"``.
* **Membership** is tested on the bar's **open** time, half-open
  ``[start, end)``: for ``0930-0945`` on 5m bars the 09:30, 09:35 and 09:40 bars are
  inside and 09:45 is not.
* **Midnight** — a range whose end is before its start (``2000-0200``) crosses
  midnight; as in Pine, an overnight range belongs to the day it **ends** on:
  ``"1700-1700:23456"`` is Sunday 17:00 → Monday 17:00 … Thursday 17:00 →
  Friday 17:00, and ``"2000-0200:2"`` is Sunday 20:00 → Monday 02:00. An end of
  ``0000`` means midnight at the end of the start day (``2000-0000`` runs
  20:00–24:00 of the masked day; ``0000-0000`` is the whole day).
* **Time zones** — every range is local wall-clock time in an IANA zone,
  converted with the rules of :mod:`kterminal.domain.sessions` (a time in the
  spring-forward gap moves forward by the gap; an ambiguous fall-back time is its
  first occurrence).

:meth:`SessionSpec.started` is Pine's ``inSess and not inSess[1]``: the bar is
inside and the previous bar was not (or there is none). Consecutive bars in two
different occurrences — a data gap across the closed hours — do not count as a
start, exactly like the script; compare :meth:`SessionSpec.window_at` when that
matters.

As parameters use :data:`SessionString` and :data:`TimeZoneName`; both are
validated, and ``SessionString`` is normalised (``"2000-0200"`` →
``"2000-0200:1234567"``), so equal windows give equal versions.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from functools import lru_cache
from typing import Annotated

from pydantic import AfterValidator, Field

from kterminal.core.clock import ensure_utc
from kterminal.domain.sessions import SessionWindow, Span, Weekday, zone

ALL_DAYS = "1234567"
_RANGE = re.compile(r"^(\d{2})(\d{2})-(\d{2})(\d{2})(?::([1-7]+))?$", re.ASCII)
# Pine numbers days from Sunday = 1; Weekday from Monday = 0.
_PINE_TO_WEEKDAY = {1: Weekday.SUN, 2: Weekday.MON, 3: Weekday.TUE, 4: Weekday.WED}
_PINE_TO_WEEKDAY |= {5: Weekday.THU, 6: Weekday.FRI, 7: Weekday.SAT}
_MIDNIGHT = time(0, 0)


@dataclass(frozen=True, slots=True)
class SessionRange:
    """One ``HHMM-HHMM:days`` range; ``days`` are Pine day numbers (1 = Sunday)."""

    start: time
    end: time
    days: frozenset[int]

    @property
    def overnight(self) -> bool:
        """Ends on the next day (and so belongs to the day it ends on)."""
        return self.end != _MIDNIGHT and self.end <= self.start

    @property
    def text(self) -> str:
        return f"{self.start:%H%M}-{self.end:%H%M}"


@dataclass(frozen=True, slots=True)
class SessionSpec:
    """A parsed session string in one time zone. Build it with :func:`parse_session`."""

    text: str  # canonical, e.g. "2000-0200:1234567"
    timezone: str
    ranges: tuple[SessionRange, ...]
    _windows: tuple[SessionWindow, ...] = field(repr=False, compare=False)

    def contains(self, ts: datetime) -> bool:
        """Whether instant ``ts`` (a bar's open time) is inside the session."""
        return self.window_at(ts) is not None

    def window_at(self, ts: datetime) -> Span | None:
        """UTC ``[start, end)`` of the occurrence containing ``ts``, or None."""
        ts = ensure_utc(ts)
        for window in self._windows:
            span = window.window_at(ts)
            if span is not None:
                return span
        return None

    def started(self, ts: datetime, previous: datetime | None) -> bool:
        """Pine's ``inSess and not inSess[1]``: the bar opening at ``ts`` is inside and
        the previous bar (opening at ``previous``; None = there is none) was not."""
        return self.contains(ts) and (previous is None or not self.contains(previous))

    def ends_by(self, open_time: datetime, close_time: datetime) -> bool:
        """Whether the bar ``[open_time, close_time)`` is inside an occurrence that ends
        at or before its close: the last bar of the window. An exit decided on it fills
        at the next open, the first price after the window."""
        span = self.window_at(open_time)
        return span is not None and span[1] <= ensure_utc(close_time)


def _parse_time(hours: str, minutes: str, text: str) -> time:
    hour, minute = int(hours), int(minutes)
    if hour > 23 or minute > 59:
        raise ValueError(f"session {text!r}: invalid time {hours}{minutes} (0000 … 2359)")
    return time(hour, minute)


def _parse_ranges(text: str) -> tuple[SessionRange, ...]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"session must be a string like '0930-1600:23456', got {text!r}")
    compact = re.sub(r"\s+", "", text)
    if compact.lower() == "24x7":
        return (SessionRange(_MIDNIGHT, _MIDNIGHT, frozenset(range(1, 8))),)
    parsed: list[tuple[time, time, str | None]] = []
    for part in compact.split(","):
        match = _RANGE.fullmatch(part)
        if match is None:
            raise ValueError(
                f"session {text!r}: {part!r} is not 'HHMM-HHMM' with an optional ':days' "
                "mask of the digits 1-7 (1 = Sunday)"
            )
        start = _parse_time(match[1], match[2], text)
        end = _parse_time(match[3], match[4], text)
        parsed.append((start, end, match[5]))
    # a mask applies to the ranges before it that have none (Pine: "0900-1600,1700-2000:23456")
    ranges: list[SessionRange] = []
    mask: str | None = None
    for start, end, own in reversed(parsed):
        mask = own if own is not None else mask
        days = frozenset(int(d) for d in (mask or ALL_DAYS))
        ranges.append(SessionRange(start, end, days))
    return tuple(reversed(ranges))


def _canonical(ranges: tuple[SessionRange, ...]) -> str:
    def mask(days: frozenset[int]) -> str:
        return "".join(str(d) for d in sorted(days))

    if len({r.days for r in ranges}) == 1:
        return ",".join(r.text for r in ranges) + ":" + mask(ranges[0].days)
    return ",".join(f"{r.text}:{mask(r.days)}" for r in ranges)


def _window(index: int, timezone: str, item: SessionRange) -> SessionWindow:
    # SessionWindow days are the days a window STARTS on; an overnight Pine range
    # belongs to the day it ends on, so it starts the day before.
    shift = 1 if item.overnight else 0
    return SessionWindow(
        id=f"session_{index}",
        name=item.text,
        timezone=timezone,
        start=item.start,
        end=item.end,
        days=frozenset(Weekday((_PINE_TO_WEEKDAY[d] - shift) % 7) for d in item.days),
    )


@lru_cache(maxsize=256)
def parse_session(text: str, timezone: str, days: str | None = None) -> SessionSpec:
    """Parse a Pine session string in IANA zone ``timezone``.

    ``days`` (``"1234567"`` or ``":23456"``) is a mask for a string that has none of
    its own, like a separate ``input.string`` of days in Pine. Results are cached
    (they are immutable)."""
    zone(timezone)  # unknown or host-dependent zones are refused
    ranges = _parse_ranges(text)
    if days is not None:
        mask = days.strip().removeprefix(":")
        if not re.fullmatch(r"[1-7]+", mask, re.ASCII):
            raise ValueError(f"days {days!r}: use the digits 1-7 (1 = Sunday), e.g. ':23456'")
        if ":" in text:
            raise ValueError(f"session {text!r} has its own days mask; do not pass days too")
        masked = frozenset(int(d) for d in mask)
        ranges = tuple(SessionRange(r.start, r.end, masked) for r in ranges)
    windows = tuple(_window(i, timezone, r) for i, r in enumerate(ranges))
    return SessionSpec(_canonical(ranges), timezone, ranges, windows)


def in_session(ts: datetime, session: str, timezone: str, days: str | None = None) -> bool:
    """Whether a bar opening at ``ts`` is inside ``session`` (Pine ``time()`` semantics)."""
    return parse_session(session, timezone, days).contains(ts)


def session_started(
    ts: datetime,
    previous: datetime | None,
    session: str,
    timezone: str,
    days: str | None = None,
) -> bool:
    """Whether the bar opening at ``ts`` starts the window: it is inside and the previous
    bar (opening at ``previous``) was not."""
    return parse_session(session, timezone, days).started(ts, previous)


# ── parameter types ──────────────────────────────────────────────────────────
def _session_text(value: str) -> str:
    return _canonical(_parse_ranges(value))


def _zone_name(value: str) -> str:
    zone(value)
    return value


SessionString = Annotated[str, AfterValidator(_session_text), Field(validate_default=True)]
"""A Pine session string as a strategy parameter: validated and normalised
(``"2000-0200"`` → ``"2000-0200:1234567"``), defaults included."""

TimeZoneName = Annotated[str, AfterValidator(_zone_name), Field(validate_default=True)]
"""An IANA time-zone name as a strategy parameter (e.g. ``"America/New_York"``)."""

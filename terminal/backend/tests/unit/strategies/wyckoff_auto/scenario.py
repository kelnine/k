"""Hand-built tapes for the script 6 Wyckoff tests.

A :class:`Tape` is a gap-free run of ``(open, high, low, close, volume)`` rows. Most bars
are written as a move of the close from the previous close with wicks around the body
(:meth:`Tape.step`); a few key bars are written out in full. ``Tape.mark`` names the
index of the last bar written, so tests can refer to "the SC bar" or "the Spring bar".

:func:`run_engine` drives :class:`WyckoffEngine` directly (bar index = row index, one
15-minute bar each) and keeps a :class:`Trace` of every step plus a snapshot of the
campaign after it, so tests can assert where each phase begins and why.

The canonical accumulation (:func:`accumulation`) is a schematic written against the
script's thresholds: a 260-bar downtrend of 0.3 per bar (range 1.0, volume 100), a
selling climax (range 2.7, volume 400), an automatic rally of about 5, a secondary test,
a 40-bar Phase B trading range with a second, quieter ST, an opposite test at the AR
high and two traversals, a Spring under the range low, its Test, a sign of strength
through the AR high, a last point of support and the markup that is Phase E. Each phase
change happens on the bar the comments name; :func:`distribution` is the same tape
mirrored (prices reflected about 300), so every rule is also exercised short.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import Timeframe
from kterminal.strategies.wyckoff_auto.state import (
    PHASE_NAMES,
    WS,
    bit_names,
)
from kterminal.strategies.wyckoff_auto.wyckoff_engine import EngineStep, Strictness, WyckoffEngine
from tests.fixtures.instruments import T0

Row = tuple[float, float, float, float, float]

MIRROR_AXIS = 300.0  # distribution(): prices reflected about this level (all stay > 0)


class Tape:
    """Consecutive rows; ``close`` is the last close, the next bar's default open."""

    def __init__(self, price: float = 200.0, volume: float = 100.0) -> None:
        self.rows: list[Row] = []
        self.close = price
        self.volume = volume
        self.marks: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self.rows)

    def bar(self, o: float, h: float, low: float, c: float, v: float | None = None) -> "Tape":
        """One bar written out in full."""
        assert low <= min(o, c) and h >= max(o, c), (o, h, low, c)
        self.rows.append((o, h, low, c, self.volume if v is None else v))
        self.close = c
        return self

    def step(
        self,
        close: float,
        *,
        up: float = 0.2,
        down: float = 0.2,
        v: float | None = None,
        open_: float | None = None,
    ) -> "Tape":
        """A bar from the previous close to ``close``, wicks ``up``/``down`` beyond the body."""
        o = self.close if open_ is None else open_
        return self.bar(o, max(o, close) + up, min(o, close) - down, close, v)

    def path(self, closes: Iterable[float], **kwargs: float) -> "Tape":
        for close in closes:
            self.step(close, **kwargs)  # type: ignore[arg-type]
        return self

    def trend(self, n: int, delta: float, *, wick: float = 0.35, v: float | None = None) -> "Tape":
        """``n`` bars each moving the close by ``delta`` (range ``|delta| + 2 * wick``)."""
        for _ in range(n):
            self.step(round(self.close + delta, 6), up=wick, down=wick, v=v)
        return self

    def flat(self, n: int, *, v: float | None = None) -> "Tape":
        """``n`` alternating bars around the current close (bodies 0.1, range 0.5): equal
        highs and equal lows, so they make no pivot."""
        level = self.close
        for i in range(n):
            if i % 2 == 0:
                self.bar(level, level + 0.25, level - 0.25, level + 0.1, v)
            else:
                self.bar(level + 0.1, level + 0.25, level - 0.25, level, v)
        self.close = level
        return self

    def mark(self, name: str) -> "Tape":
        """Name the last bar written."""
        self.marks[name] = len(self.rows) - 1
        return self

    def mirrored(self, axis: float = MIRROR_AXIS) -> "Tape":
        """The tape reflected about ``axis``: an accumulation becomes a distribution."""
        out = Tape(round(2 * axis - self.close, 6), self.volume)
        for o, h, low, c, v in self.rows:
            out.rows.append(
                (
                    round(2 * axis - o, 6),
                    round(2 * axis - low, 6),
                    round(2 * axis - h, 6),
                    round(2 * axis - c, 6),
                    v,
                )
            )
        out.close = round(2 * axis - self.close, 6)
        out.marks = dict(self.marks)
        return out

    def bars(
        self, *, start: datetime = T0, timeframe: str = "15m", instrument: str = "XAUUSD"
    ) -> list[Bar]:
        tf = Timeframe.parse(timeframe)
        return [
            Bar.of(instrument, tf, start + i * tf.duration, repr(o), repr(h), repr(low), repr(c), v)
            for i, (o, h, low, c, v) in enumerate(self.rows)
        ]


@dataclass(slots=True)
class Snapshot:
    """The campaign after one bar (the fields the tests look at)."""

    serial: int
    phase: str
    outcome: int
    stop_side: int
    ev: int
    range_high: float
    range_low: float
    st_count: int
    opp_count: int
    trav_count: int
    exc: bool
    exc_tested: bool
    entry_time: float
    entry_kind: int


@dataclass(slots=True)
class Trace:
    """Every step of an engine run, with the campaign after each bar."""

    steps: list[EngineStep] = field(default_factory=list)
    after: list[Snapshot] = field(default_factory=list)
    engine: WyckoffEngine | None = None

    def phases(self) -> list[str]:
        return [s.phase for s in self.after]

    def first(self, phase: str) -> int:
        """Index of the first bar after which the campaign is in ``phase``."""
        return self.phases().index(phase)

    def events(self, name: str) -> list[int]:
        """Bars whose event bits include ``name`` (``bit_names``)."""
        return [i for i, s in enumerate(self.steps) if name in bit_names(s.sig)]

    def ends(self, kind: str) -> list[int]:
        """Bars on which a campaign ended (or demoted) with ``kind``."""
        return [i for i, s in enumerate(self.steps) if any(e.kind == kind for e in s.ends)]

    def entries(self) -> list[int]:
        return [
            i for i, s in enumerate(self.steps) if s.entry_check is not None and s.entry_check.taken
        ]

    def describe(self, start: int = 0, stop: int | None = None) -> str:
        """A readable log of the phase changes and events (for failing assertions)."""
        lines = []
        previous = None
        for i, (step, snap) in enumerate(zip(self.steps, self.after, strict=True)):
            if i < start or (stop is not None and i >= stop):
                continue
            names = bit_names(step.sig)
            ends = [e.kind for e in step.ends]
            if names or ends or snap.phase != previous or step.entry_check is not None:
                check = step.entry_check
                lines.append(
                    f"{i}: phase {snap.phase} out {snap.outcome} {names} {ends}"
                    + (
                        f" entry {check.triggers} conf {check.confidence} val "
                        f"{check.validation} ready {check.readiness}"
                        if check is not None
                        else ""
                    )
                )
            previous = snap.phase
        return "\n".join(lines)


def snapshot(s: WS) -> Snapshot:
    return Snapshot(
        serial=s.serial,
        phase=PHASE_NAMES[s.phase],
        outcome=s.outcome,
        stop_side=s.stop_side,
        ev=s.ev,
        range_high=s.range_high,
        range_low=s.range_low,
        st_count=s.st_count,
        opp_count=s.opp_count,
        trav_count=s.trav_count,
        exc=s.exc,
        exc_tested=s.exc_tested,
        entry_time=s.entry_time,
        entry_kind=s.entry_kind,
    )


def run_engine(
    rows: Sequence[Row] | Tape,
    *,
    strictness: Strictness = "Standard",
    mintick: float = 0.01,
    tf_seconds: float = 900.0,
    start: datetime = T0,
) -> Trace:
    """The engine over ``rows``: bar ``i`` opens at ``start + i × tf_seconds``."""
    data = rows.rows if isinstance(rows, Tape) else rows
    engine = WyckoffEngine(mintick, tf_seconds, strictness)
    trace = Trace(engine=engine)
    for i, (o, h, low, c, v) in enumerate(data):
        time_ms = (start + timedelta(seconds=tf_seconds * i)).timestamp() * 1000.0
        trace.steps.append(engine.update(i, time_ms, o, h, low, c, v))
        trace.after.append(snapshot(engine.s))
    return trace


# ── the canonical accumulation ──────────────────────────────────────────────────────────
STAGES = ("sc", "st", "phase_b", "spring", "test", "sos", "lps", "markup")

# Bars of the canonical accumulation (row indexes): where each event is written and the
# bar on which the engine confirms it (a pivot is confirmed pLen = 4 bars later).
SC = 260  # selling climax (seeds Phase A); absorption confirms it at 263
AR_PEAK = 266  # the automatic rally's high, 124.6
ST1 = 272  # first secondary test (pivot); AR + ST + Phase B at 276
OPP = 280  # opposite test at the AR high (pivot), registered at 284
ST2 = 289  # second, quieter ST (pivot), registered at 293
SPRING = 308  # Spring under the range low: Phase C at once (Phase B is mature)
TEST = 314  # its Test (pivot), confirmed at 318: the Standard / Aggressive entry
SOS = 323  # sign of strength through the AR high: Phase D
LPS = 329  # last point of support (pivot), confirmed at 333: the Conservative entry
PHASE_E = 336  # three closes above the range after the LPS: Phase E (markup)
RANGE_HIGH = 124.6  # the AR high
SPRING_LOW = 119.2


def accumulation(stage: str = "markup") -> Tape:
    """The canonical accumulation up to and including ``stage`` (see the module docstring)."""
    last = STAGES.index(stage)
    t = Tape(200.0)
    t.trend(SC, -0.3)  # 0-259: downtrend, ATR ≈ 1.0, trend score ≈ -46 (strong)
    c = t.close
    t.bar(c, c + 0.2, c - 2.5, c - 1.2, 400).mark("sc")  # 260: SC, low 119.5, volume 4x
    t.path([round(t.close + 0.6 * k, 6) for k in range(1, 7)]).mark("ar")  # 261-266: AR
    if last < STAGES.index("st"):
        return t
    t.path([123.6, 122.8, 122.0, 121.2, 120.6])  # 267-271
    t.bar(120.6, 121.1, 120.1, 120.95).mark("st1")  # 272: ST1, 0.6 above the SC low
    t.path([121.4, 121.9, 122.3, 122.7])  # 273-276: ST1 confirmed, Phase B from 272
    if last < STAGES.index("phase_b"):
        return t
    t.path([123.1, 123.5, 123.8])  # 277-279
    t.bar(123.8, 124.3, 123.6, 124.0).mark("opp")  # 280: opposite test at the AR high
    t.path([123.6, 123.2, 122.8, 122.4])  # 281-284: registered (traversal 1)
    t.path([122.0, 121.6, 121.2, 120.8])  # 285-288
    t.bar(120.8, 121.0, 120.2, 120.85, 80).mark("st2")  # 289: ST2, volume 80, range 0.8
    t.path([121.2, 121.6, 122.0, 122.3])  # 290-293: registered (traversal 2)
    t.flat(10)  # 294-303: mid-range; Phase B is mature from bar 302 (30 bars)
    if last < STAGES.index("spring"):
        return t
    t.path([121.8, 121.3, 120.8, 120.4])  # 304-307: back to the range low
    t.bar(120.4, 121.1, SPRING_LOW, 120.95, 140).mark("spring")  # 308: Spring, recovers
    if last < STAGES.index("test"):
        return t
    t.path([121.3, 121.5, 121.1, 120.6, 120.2])  # 309-313
    t.bar(120.2, 120.5, 119.7, 120.35, 80).mark("test")  # 314: Test, quiet, holds
    t.path([120.7, 121.1, 121.5, 121.9])  # 315-318: confirmed at 318 -> entry
    if last < STAGES.index("sos"):
        return t
    t.path([122.3, 122.7, 123.1, 123.5])  # 319-322
    t.bar(123.5, 125.3, 123.4, 125.2, 220).mark("sos")  # 323: SOS, closes through 124.6
    if last < STAGES.index("lps"):
        return t
    t.path([125.6, 125.8])  # 324-325
    t.path([125.2, 124.6, 124.1])  # 326-328
    t.bar(124.1, 124.3, 123.7, 124.2, 80).mark("lps")  # 329: LPS, above the creek - 1.5 ATR
    t.path([124.6, 125.0, 125.4, 125.8])  # 330-333: confirmed at 333
    if last < STAGES.index("markup"):
        return t
    t.path([126.2, 126.6, 127.0])  # 334-336: three closes above 124.6 -> Phase E at 336
    return t


def distribution(stage: str = "markup") -> Tape:
    """The canonical accumulation mirrored about 300: an uptrend, a buying climax, an
    automatic reaction, an UTAD, its Test, a SOW, an LPSY and the markdown."""
    return accumulation(stage).mirrored()

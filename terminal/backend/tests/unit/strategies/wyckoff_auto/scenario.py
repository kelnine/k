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

    def flat(self, n: int, *, v: float | None = None, half: float = 0.25) -> "Tape":
        """``n`` alternating bars around the current close (bodies 0.1, range ``2 * half``):
        equal highs and equal lows, so they make no pivot."""
        level = self.close
        hi, lo = round(level + half, 6), round(level - half, 6)
        for i in range(n):
            if i % 2 == 0:
                self.bar(level, hi, lo, round(level + 0.1, 6), v)
            else:
                self.bar(round(level + 0.1, 6), hi, lo, level, v)
        self.close = level
        return self

    def cut(self, n: int) -> "Tape":
        """Keep the first ``n`` rows (the marks after them are dropped)."""
        self.rows = self.rows[:n]
        self.close = self.rows[-1][3]
        self.marks = {k: i for k, i in self.marks.items() if i < n}
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


# ── targeted variants (each comment names the bar the engine acts on) ─────────────────────
def absorption_fails() -> Tape:
    """SC at 260, then the effort dries up (volume 50): no absorption within 8 bars, so
    the climax is retired at 269 (RS_ABSORB, L1186/L1193)."""
    t = accumulation("sc").cut(SC + 1)
    t.path([121.2, 121.6, 122.0, 122.3, 122.6, 122.9, 123.1, 123.3, 123.5, 123.6], v=50)
    return t


def no_automatic_rally() -> Tape:
    """SC at 260, absorbed at 263, but the rally peaks 1.8 ATR above the SC low and the
    range stays flat: no AR within 30 bars, retired at 291 (RS_NORANGE, L1187/L1195)."""
    t = accumulation("sc").cut(SC + 1)
    t.path([120.9, 121.0, 121.0, 120.9, 120.8], up=0.3, down=0.3)
    t.flat(40, half=0.5)  # range 1.0 keeps the ATR at about 1
    return t


def phase_a_invalidated() -> Tape:
    """SC at 260 (low 119.5), then two closes more than 0.5 ATR below it: retired at 264
    (RS_INVALID in Phase A, L1184/L1191)."""
    t = accumulation("sc").cut(SC + 1)
    t.path([120.5, 119.6, 118.8, 118.7, 118.6])
    return t


def phase_b_goes_stale() -> Tape:
    """Phase B (last activity: the ST2 registration at 293), then 130 quiet bars in the
    middle of the range: retired at 419, 126 bars later (RS_STALE, limit 125, L1226)."""
    t = accumulation("phase_b")
    t.flat(130)
    return t


def phase_b_departs() -> Tape:
    """Phase B, then price walks out above the range without any Spring: three closes
    above the AR high + max(0.35 x height, 0.75 ATR) retire it at 310 (RS_DEPART, L1649,
    L1661)."""
    t = accumulation("phase_b")
    t.path([123.0, 124.0, 125.0, 126.0, 126.8, 127.3, 127.8, 128.2, 128.6])
    return t


PROVISIONAL = 297  # a probe under the range low while Phase B is still immature
ADOPTED = 312  # the breakout adopts it: Spring + SOS, Phase D on one bar


def provisional_spring() -> Tape:
    """A Spring-like probe at 297, before Phase B is mature (bar 302), is kept as a
    provisional Spring (L1576-1586); the breakout after maturity adopts it and promotes
    straight to Phase D at 312 (L1654-1660): no Phase C test, so only Aggressive enters
    (its SOS fallback, L1740)."""
    t = accumulation("phase_b").cut(ST2 + 5)  # through 293, ST2 registered
    t.path([121.6, 121.0, 120.4])  # 294-296
    t.bar(120.4, 120.9, 119.4, 120.8).mark("provisional")  # 297: 0.4 under 119.825
    t.path([121.3, 121.8, 122.2, 122.6, 122.9])  # 298-302
    t.flat(4)  # 303-306
    t.path([123.4, 123.9, 124.3])  # 307-309
    t.bar(124.3, 125.6, 124.2, 125.5, 250)  # 310: closes through the AR high
    t.bar(125.5, 126.4, 125.4, 126.3, 220)  # 311
    t.path([126.6, 126.9, 127.2])  # 312-314
    return t


C_TEST = 308  # the quiet pivot low of the terminal test
C_TEST_CONFIRMED = 312


def terminal_test() -> Tape:
    """No Spring: once Phase B is mature, a quiet pivot low at 308 within 1.25 ATR of the
    range low (holding the ST2 low) is the terminal C-Test, confirmed at 312 (L1328-1348):
    Phase C with a test — the Standard and Aggressive entry."""
    t = accumulation("phase_b")  # through 303
    t.path([121.8, 121.3, 120.9, 120.6])  # 304-307
    t.bar(120.6, 120.7, 120.3, 120.55, 60).mark("c_test")  # 308
    t.path([120.9, 121.3, 121.7, 122.1, 122.5, 122.9, 123.3])  # 309-315
    return t


def phase_c_invalidated() -> Tape:
    """After the Test entry (318), two closes more than 0.5 ATR under the Spring low
    (119.2): the campaign is retired at 323 (RS_INVALID, L1199)."""
    t = accumulation("test")
    t.path([121.0, 120.0, 119.0, 118.4, 118.2, 118.0])
    return t


STALE_C = 369
NEW_SC = 424


def phase_c_goes_stale_then_new_climax() -> Tape:
    """After the Test entry (318) nothing happens for 50 bars: the campaign goes stale at
    369 (RS_STALE, limit 50 in Phase C); a downtrend later ends in a new selling climax
    that seeds a campaign at 424."""
    t = accumulation("test")
    t.flat(60)  # 319-378
    t.trend(45, -0.3)  # 379-423
    c = t.close
    t.bar(c, c + 0.2, c - 2.5, c - 1.2, 400).mark("sc2")  # 424
    t.path([round(t.close + 0.6 * k, 6) for k in range(1, 4)])  # 425-427
    return t


DEMOTED = 329


def phase_d_demoted() -> Tape:
    """After the SOS (323), three closes back under the range middle (122.21): Phase D is
    demoted to B at 329 (L1210-1211); the campaign keeps its entry (L909-930)."""
    t = accumulation("sos")
    t.path([124.6, 123.6, 122.4, 121.6, 121.4, 121.3])
    return t


def phase_d_invalidated() -> Tape:
    """After the SOS, a collapse: two closes more than 0.5 ATR under the Spring low before
    three closes under the middle — RS_INVALID at 327 (L1208)."""
    t = accumulation("sos")
    t.path([124.8, 121.0, 118.0, 117.9, 117.8])
    return t


RETEST = 343


def demoted_then_tested_again() -> Tape:
    """Demoted at 329, the campaign forms a new Spring (333) and its Test (343) — a
    qualifying Phase C test that cannot enter: entryTime survived the demotion."""
    t = phase_d_demoted()
    t.path([121.0, 120.6, 120.3])  # 330-332
    t.bar(120.3, 120.9, 119.3, 120.8, 140).mark("spring2")  # 333
    t.path([121.2, 121.4, 121.0, 120.6, 120.3])  # 334-338
    t.bar(120.3, 120.6, 119.8, 120.45, 70).mark("test2")  # 339
    t.path([120.8, 121.2, 121.6, 122.0, 122.4])  # 340-344
    return t


RE_SOS = 334


def re_sos() -> Tape:
    """After the LPS (333), a wide, high-effort close above the AR high is a renewed SOS
    at 334 (L1678-1685)."""
    t = accumulation("lps")
    t.bar(125.8, 126.9, 125.7, 126.8, 250)  # 334
    return t


E_FAILED = 342


def phase_e_fails() -> Tape:
    """Phase E (336), then three closes back under the range middle: RS_EEND at 342
    (L1221)."""
    t = accumulation()
    t.path([126.0, 124.5, 123.0, 122.0, 121.8, 121.6])
    return t


E_TIMEOUT = 637


def phase_e_times_out() -> Tape:
    """Phase E (336) holds above the range for more than 300 bars: RS_EEND at 637
    (L1222)."""
    t = accumulation()
    t.flat(305)
    return t


RESEEDED = 377


def phase_e_replaced() -> Tape:
    """Phase E (336), the markup runs on and ends in a buying climax at 377 that seeds a
    distribution campaign in place of the accumulation (L1237, L1260-1271)."""
    t = accumulation()
    t.trend(40, 0.3)  # 337-376
    c = t.close
    t.bar(c, c + 2.5, c - 0.2, c + 1.0, 400).mark("bc")  # 377
    t.path([round(t.close - 0.6 * k, 6) for k in range(1, 5)])  # 378-381
    return t

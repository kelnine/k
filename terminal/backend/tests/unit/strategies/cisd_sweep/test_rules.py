"""Golden scenarios for S6 (script 1's main CISD model): each rule fires on a known bar and
each blocking condition blocks.

The tapes run in New York time from Monday 18:00 (a partial trading day, so no PDH/PWH/
PMH yet) with a wide bar at the start of every session, which puts the session highs and
lows (and the pivots they make) ±10 away; the scenario is ``scenario.BEAR_SETUP``: a 5/5
pivot high swept, an up-close run, a close through its open.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import OrderType, SignalAction
from kterminal.strategies.cisd_sweep import CisdSweep
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.unit.strategies.cisd_sweep.scenario import (
    BEAR_SETUP,
    FILL_AND_TARGET,
    RUN_AT,
    SESSION_STARTS,
    SIGNAL_AT,
    SWEEP_AT,
    Row,
    Tape,
    bar_offset,
    ny,
    quiet_row,
    run_tape,
)
from tests.unit.strategies.pine_port_support import of_kind

DAY = date(2026, 1, 6)  # a Tuesday in winter (New York = UTC-5)
LONG, SHORT = SignalAction.LONG, SignalAction.SHORT


def tape_at(
    hhmm: str, *rows: Row, day: date = DAY, tail: int = 30, level: float = 99.6
) -> tuple[Tape, Any]:
    """Monday 18:00 → the rows at ``hhmm`` New York on ``day`` → ``tail`` quiet bars."""
    tape = Tape(ny(day - timedelta(days=1), "18:00"), wide=SESSION_STARTS)
    anchor = ny(day, hhmm)
    tape.at(anchor, *rows).quiet(tail, level=level)
    return tape, anchor


def cisd(tape: Tape, params: dict[str, Any] | None = None, **kwargs: Any) -> StrategyTestResult:
    return run_tape(CisdSweep, tape, params=params, **kwargs)


@pytest.mark.parametrize(
    "day", [DAY, date(2026, 3, 10), date(2026, 7, 7)], ids=["winter", "first-EDT-week", "summer"]
)
def test_bearish_cisd_after_a_pivot_sweep_rests_a_limit_at_the_level(day: date) -> None:
    tape, anchor = tape_at("06:00", *BEAR_SETUP, *FILL_AND_TARGET, day=day, level=98.4)
    result = cisd(tape)
    (signal,) = result.signals
    assert signal.bar_time == anchor + SIGNAL_AT * tape.timeframe.duration
    assert (signal.signal, signal.order_type) == (SHORT, OrderType.LIMIT)
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("100.00"),
        Decimal("100.80"),  # the run's high, inside the sweep wick (101.5)
        Decimal("98.40"),  # TP2 = entry − 2R, R = 0.8
    )
    assert signal.expires_after_bars == 12
    meta = signal.metadata
    assert (meta["trigger"], meta["pine_signal"], meta["model"]) == (
        "Bearish CISD",
        "bearCisd",
        "main",
    )
    first = meta["bar_index"]
    assert isinstance(first, int)
    assert meta["sweep"] == {
        "bar_index": first - (SIGNAL_AT - SWEEP_AT),
        "bars_ago": SIGNAL_AT - SWEEP_AT,
        "time": (anchor + SWEEP_AT * tape.timeframe.duration).isoformat(),
        "levels": [{"level": "pivot high", "price": 101.0}],
    }
    assert meta["run_start_bar_index"] == first - (SIGNAL_AT - RUN_AT)
    assert (meta["run_bars"], meta["cisd_level"], meta["run_extreme"]) == (3, 100.0, 100.8)
    assert meta["script_tp1"] == pytest.approx(99.2) and meta["script_tp2"] == pytest.approx(98.4)
    assert meta["risk_points"] == pytest.approx(0.8)
    assert meta["body"] == pytest.approx(1.1)
    assert isinstance(meta["atr"], float) and meta["min_body_points"] == pytest.approx(
        0.3 * meta["atr"]
    )
    levels = meta["levels"]
    assert isinstance(levels, dict)
    assert (levels["Asia high"], levels["LNDN low"], levels["NY AM high"]) == (110.0, 90.0, None)
    assert levels["PDH"] is None and levels["pivot high"] is None  # partial day; cleared
    assert (meta["entry_mode"], meta["target_leg"], meta["sig_window"]) == (
        "limit",
        "tp2",
        "Any time",
    )

    (opened,) = of_kind(result, PositionEventKind.OPENED)
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (tape.index(opened.time) - tape.index(anchor), opened.price) == (
        11,
        Decimal("100.00"),
    )
    assert (closed.reason, closed.price) == (CloseReason.TAKE_PROFIT, Decimal("98.40"))
    assert closed.time == anchor + 14 * tape.timeframe.duration  # the close of +13


def test_the_bullish_setup_mirrors_the_bearish_one() -> None:
    tape, anchor = tape_at("06:00", *BEAR_SETUP, *FILL_AND_TARGET, level=98.4)
    result = cisd(tape, mirror=True)
    (signal,) = result.signals
    assert (bar_offset(tape, signal, anchor), signal.signal) == (SIGNAL_AT, LONG)
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("100.00"),
        Decimal("99.20"),
        Decimal("101.60"),
    )
    assert (signal.metadata["trigger"], signal.metadata["pine_signal"]) == (
        "Bullish CISD",
        "bullCisd",
    )
    sweep = signal.metadata["sweep"]
    assert isinstance(sweep, dict) and sweep["levels"] == [{"level": "pivot low", "price": 99.0}]
    (closed,) = of_kind(result, PositionEventKind.CLOSED)
    assert (closed.reason, closed.price) == (CloseReason.TAKE_PROFIT, Decimal("101.60"))


def test_no_sweep_no_signal_unless_the_sweep_is_not_required() -> None:
    rows = list(BEAR_SETUP)
    rows[SWEEP_AT] = (100.1, 100.15, 99.85, 100.0)  # the high stays below the pivot
    tape, anchor = tape_at("06:00", *rows)
    assert cisd(tape).signals == []
    # reqSweep off (L661, L668): the bearish CISD fires; so does a bullish one at +8, whose
    # close (100.5) crosses the open of the quiet down run before it (100.1) — its limit
    # is cancelled at +9, where TP1 (100.35) trades before the fill
    loose = cisd(tape, {"req_sweep": False}).signals
    assert [(bar_offset(tape, s, anchor), s.signal) for s in loose] == [
        (8, LONG),
        (9, SignalAction.EXIT_LONG),
        (SIGNAL_AT, SHORT),
    ]
    assert loose[1].metadata["detail"] == "TP1 traded before the fill"


@pytest.mark.parametrize(("gap", "fires"), [(9, True), (10, False)])
def test_the_sweep_must_be_within_sweep_look_bars(gap: int, fires: bool) -> None:
    # gap quiet bars between the sweep and the run: the CISD is 3 + gap bars after it
    rows = [*BEAR_SETUP[: SWEEP_AT + 1]]
    rows += [quiet_row(i + 1) for i in range(gap)]  # starts with a down bar closing 100.0
    rows += BEAR_SETUP[RUN_AT:]
    tape, anchor = tape_at("06:00", *rows)
    signals = cisd(tape).signals
    if fires:
        (signal,) = signals
        sweep = signal.metadata["sweep"]
        assert isinstance(sweep, dict) and sweep["bars_ago"] == 12  # sweepLook (L661)
        assert bar_offset(tape, signal, anchor) == SIGNAL_AT + gap
    else:
        assert signals == []
    shorter = cisd(tape, {"sweep_look": 3 + gap - 1}).signals
    assert shorter == []


def test_a_weak_close_through_the_level_consumes_it() -> None:
    rows = [
        *BEAR_SETUP[:RUN_AT],
        (100.0, 100.1, 99.95, 100.04),  # +8 up-close run: open 100.0
        (100.04, 100.06, 99.9, 99.98),  # +9 close < 100.0, body 0.06 < 0.3 ATR: no CISD
        (99.98, 100.0, 99.3, 99.4),  # +10 a strong close below 100.0: the level is gone
        (99.4, 99.9, 99.35, 99.8),  # +11 a new up-close run: open 99.4
        (99.8, 99.85, 99.0, 99.1),  # +12 close < 99.4: bearish CISD on the new level
    ]
    tape, anchor = tape_at("06:00", *rows, level=99.1)
    (signal,) = cisd(tape).signals
    assert bar_offset(tape, signal, anchor) == 12
    assert (signal.entry, signal.stop_loss) == (Decimal("99.40"), Decimal("99.90"))
    threshold = signal.metadata["min_body_points"]
    assert isinstance(threshold, float) and 0.06 < threshold < 0.7
    # without the body filter the weak close is the CISD, and +12 replaces it
    loose = cisd(tape, {"min_body": 0.0}).signals
    assert [bar_offset(tape, s, anchor) for s in loose if s.signal.is_entry] == [9, 12]


def test_any_body_passes_while_the_atr_is_still_na() -> None:
    # nz(atr) is 0 for the first 13 bars (L631): a 0.03 body passes on bar 3 but not later
    rows: list[Row] = [
        (100.0, 100.15, 99.85, 100.1),  # 0
        (100.1, 100.15, 99.85, 100.0),  # 1
        (100.0, 100.15, 99.85, 100.02),  # 2 up-close run: open 100.0
        (100.02, 100.05, 99.9, 99.99),  # 3 close 99.99 < 100.0, body 0.03
    ]
    # quiet below 100.02 (the bar-3 down run's open) so nothing crosses it
    tape = Tape(ny(DAY, "00:00")).then(*rows).quiet(36, level=99.9)
    tape.then((99.9, 100.05, 99.75, 99.92), (99.92, 99.95, 99.8, 99.89)).quiet(6, level=99.8)
    result = cisd(tape, {"req_sweep": False})
    assert [tape.index(s.bar_time) for s in result.signals if s.signal.is_entry] == [3]
    signal = result.signals[0]
    assert signal.metadata["atr"] is None and signal.metadata["min_body_points"] == 0.0


def test_a_doji_ends_the_run_and_the_next_up_close_starts_a_new_one() -> None:
    rows = [
        *BEAR_SETUP[:RUN_AT],
        (100.0, 100.6, 99.95, 100.5),  # +8 run open 100.0
        (100.5, 100.7, 100.4, 100.5),  # +9 doji: not an up-close bar
        (100.5, 100.9, 100.45, 100.8),  # +10 a new run: open 100.5
        (100.8, 100.85, 99.7, 99.8),  # +11 close < 100.5: the CISD level is 100.5
    ]
    tape, anchor = tape_at("06:00", *rows, level=99.8)
    signal, cancel = cisd(tape).signals  # TP1 (100.1) trades on +12: cancelled
    assert (bar_offset(tape, cancel, anchor), cancel.signal) == (12, SignalAction.EXIT_SHORT)
    assert bar_offset(tape, signal, anchor) == 11
    assert (signal.entry, signal.stop_loss) == (Decimal("100.50"), Decimal("100.90"))
    assert signal.metadata["run_bars"] == 2


def test_the_stop_includes_the_cisd_bar_and_resets_with_each_new_run() -> None:
    rows = list(BEAR_SETUP)
    rows[SIGNAL_AT] = (100.7, 101.0, 99.5, 99.6)  # the CISD bar's high tops the run
    tape, _ = tape_at("06:00", *rows)
    (signal,) = cisd(tape).signals
    assert signal.stop_loss == Decimal("101.00")  # updated before the CISD check (L643-645)
    # the default scenario: the newest run (from +8) sets the stop, not the sweep's 101.5
    tape, _ = tape_at("06:00", *BEAR_SETUP)
    (signal,) = cisd(tape).signals
    assert signal.stop_loss == Decimal("100.80")


@pytest.mark.parametrize(
    ("window", "hhmm", "fires"),
    [
        ("Any time", "06:00", True),
        ("NY AM", "06:00", False),
        ("NY AM", "10:00", True),
        ("London + NY AM", "03:00", True),
        ("London + NY AM", "06:00", False),
        ("NY AM + NY PM", "13:30", True),
        ("London + NY AM + NY PM", "15:00", True),
        ("London + NY AM + NY PM", "17:00", False),
    ],
)
def test_the_signal_window_gates_by_the_cisd_bar_open_time(
    window: str, hhmm: str, fires: bool
) -> None:
    tape, anchor = tape_at(hhmm, *BEAR_SETUP)
    signals = cisd(tape, {"sig_window": window}).signals
    assert [bar_offset(tape, s, anchor) for s in signals] == ([SIGNAL_AT] if fires else [])


def test_session_windows_are_parameters() -> None:
    # the same CISD at 06:00 falls inside a London session moved to 05:00-07:00
    tape, anchor = tape_at("06:00", *BEAR_SETUP)
    params = {"sig_window": "London + NY AM", "lon_sess": "0500-0700"}
    (signal,) = cisd(tape, params).signals
    assert bar_offset(tape, signal, anchor) == SIGNAL_AT

"""Golden scenarios for S10 (script 1's MTF scanner CISD): the 5m slot's own model (3/3
swings only, no session or previous-period levels), the A+ grade against the 15m, 1h
and 4h swing-break biases, the A+-only variant, the shared D7 order handling, params
and determinism."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError

from kterminal.core.enums import OrderType, SignalAction
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import H1, H4, M5, M15
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategies.cisd_scanner import HIGHER_SLOTS, CisdScanner, CisdScannerParams
from kterminal.strategies.cisd_sweep import CisdSweep
from kterminal.strategy_engine import PositionEventKind
from kterminal.strategy_engine.registry import definition_from_class
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import T0
from tests.unit.strategies.cisd_sweep.scenario import (
    BEAR_SETUP,
    FILL_AND_TARGET,
    SESSION_STARTS,
    SIGNAL_AT,
    TP1_FIRST,
    Row,
    Tape,
    mirrored,
    ny,
    run_tape,
)
from tests.unit.strategies.pine_port_support import dumps, make_bars, run

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT


def with_slots(five: list[Bar]) -> list[Bar]:
    """The 5m bars plus the 15m, 1h and 4h bars the lab's aggregator closes from them."""
    return [b for batch in aggregate_stream(five, M5, [M15, H1, H4]) for b in batch]


def scanner(bars: list[Bar], params: dict[str, Any] | None = None) -> StrategyTestResult:
    result = run(CisdScanner, bars, params=params, context_timeframes=HIGHER_SLOTS)
    assert result.fault is None and result.rejected == []
    return result


def slots_of(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The ``slots`` rows of a scanner signal's metadata."""
    return cast(dict[str, dict[str, Any]], metadata["slots"])


def shifted(row: Row, by: float) -> Row:
    return (row[0] + by, row[1] + by, row[2] + by, row[3] + by)


# ── A+: a tape whose 15m, 1h and 4h biases all turn bearish ───────────────────────────
def ramp(start: float, end: float, bars: int, wick: float = 0.05) -> list[Row]:
    rows: list[Row] = []
    previous = start
    for k in range(1, bars + 1):
        close = round(start + (end - start) * k / bars, 4)
        rows.append((previous, max(previous, close) + wick, min(previous, close) - wick, close))
        previous = close
    return rows


def flat(level: float, bars: int) -> list[Row]:
    return [(level, level + 0.05, level - 0.05, level)] * bars


# From Monday 00:00 UTC (4h-aligned): flat at 100 until 12:00, down to 95 by 16:00 (the
# swing low 94.9 of every slot), up from 95.5 to 110 by 40:00, flat, down to 90 by 48:00
# — every slot closes below its swing low: bias −1 — then flat at 90 until 56:00, where
# the 5m scenario (BEAR_SETUP shifted to 90) sweeps a 5m swing high and closes through.
BEARISH_HTF: list[Row] = [
    *flat(100.0, 144),
    *ramp(100.0, 95.0, 48, wick=0.1),
    *ramp(95.5, 110.0, 288),
    *flat(110.0, 48),
    *ramp(110.0, 90.0, 48),
    *flat(90.0, 96),
]
SETUP_AT = len(BEARISH_HTF)  # 56:00


def aplus_tape(*, long: bool = False, after: tuple[Row, ...] = ()) -> list[Bar]:
    setup = [shifted(r, -10.0) for r in (*BEAR_SETUP, *after)]
    if long:  # the mirrored 5m setup (a long) under the same bearish slots
        setup = [mirrored(r, 90.0) for r in setup]
    rows = [*BEARISH_HTF, *setup, *flat(setup[-1][3], 14)]
    return with_slots(make_bars(rows, start=T0))


def test_a_short_that_agrees_with_every_higher_bias_is_a_plus() -> None:
    result = scanner(aplus_tape())
    entries = [s for s in result.signals if s.signal.is_entry]
    (signal,) = entries
    assert signal.bar_time == T0 + (SETUP_AT + SIGNAL_AT) * M5.duration
    assert (signal.signal, signal.order_type) == (SHORT, OrderType.LIMIT)
    assert (signal.entry, signal.stop_loss, signal.take_profit) == (
        Decimal("90.00"),
        Decimal("90.80"),
        Decimal("88.40"),
    )
    meta = signal.metadata
    assert (meta["trigger"], meta["pine_signal"], meta["model"]) == (
        "Scanner: new A+ signal",
        "scanCisd",
        "scanner",
    )
    assert meta["aplus"] is True
    assert meta["sweep"] == {
        "bar_index": SETUP_AT + 7,
        "bars_ago": 3,
        "level": "swing high",
        "price": 91.0,
    }
    assert {tf: row["bias"] for tf, row in slots_of(meta).items()} == {
        "15m": -1,
        "1h": -1,
        "4h": -1,
    }
    assert meta["alert_text"] == (
        "A+ XAUUSD 5m: SHORT CISD  Entry 90.00  SL 90.80  TP1 89.20  TP2 88.40"
    )
    # the A+-only variant trades it too
    assert dumps(scanner(aplus_tape(), {"aplus_only": True}))[0]["metadata"]["aplus"] is True


def test_a_long_against_the_higher_biases_is_not_a_plus() -> None:
    plain = scanner(aplus_tape(long=True))
    (signal,) = [s for s in plain.signals if s.signal.is_entry]
    assert signal.signal is LONG and signal.metadata["aplus"] is False
    assert signal.metadata["trigger"] == "Scanner: new signal"
    assert signal.metadata["alert_text"] == (
        "XAUUSD 5m: LONG CISD  Entry 90.00  SL 89.20  TP1 90.80  TP2 91.60"
    )
    assert scanner(aplus_tape(long=True), {"aplus_only": True}).signals == []


def test_a_disabled_slot_does_not_count_and_no_slot_means_no_a_plus() -> None:
    meta = scanner(aplus_tape(), {"on4": False}).signals[0].metadata
    assert meta["aplus"] is True
    assert slots_of(meta)["4h"]["on"] is False
    off = {"on2": False, "on3": False, "on4": False}
    assert scanner(aplus_tape(), off).signals[0].metadata["aplus"] is False


def test_before_the_4h_break_closes_the_short_is_not_a_plus() -> None:
    # cut the tape so that the setup comes while the last 4h bar (44:00-48:00) is still
    # open: its close below the swing low is not visible yet (lookahead_on with [1])
    rows = [*BEARISH_HTF[: 48 * 12 - 12], *[shifted(r, -10.0) for r in BEAR_SETUP]]
    rows += flat(rows[-1][3], 30)
    result = scanner(with_slots(make_bars(rows, start=T0)))
    entries = [s for s in result.signals if s.signal.is_entry]
    assert entries and entries[-1].metadata["aplus"] is False
    assert slots_of(entries[-1].metadata)["4h"]["bias"] == 0


# ── the scanner's own model differs from the main one ──────────────────────────────────
DAY = date(2026, 1, 6)


def test_a_3_3_swing_sweep_counts_for_the_scanner_but_not_for_the_5_5_main_model() -> None:
    # the spike is a 3/3 swing (confirmed at +3) but never a 5/5 pivot: +4 trades above it
    rows: list[Row] = [
        (100.0, 101.0, 99.85, 100.1),  # +0 swing high 101.0
        (100.1, 100.15, 99.85, 100.0),  # +1
        (100.0, 100.15, 99.85, 100.1),  # +2
        (100.1, 100.15, 99.85, 100.0),  # +3 3/3 confirmed
        (100.0, 101.5, 99.85, 100.1),  # +4 sweep of the 3/3 swing
        (100.1, 100.15, 99.85, 100.0),  # +5
        *BEAR_SETUP[8:],  # +6 run, +7 run high 100.8, +8 CISD
    ]
    tape = Tape(ny(DAY - timedelta(days=1), "18:00"), wide=SESSION_STARTS)
    anchor = ny(DAY, "06:00")
    tape.at(anchor, *rows).quiet(20, level=99.6)
    five = tape.bars()
    (signal, *_) = scanner(with_slots(five)).signals
    assert signal.bar_time == anchor + 8 * M5.duration
    assert signal.metadata["sweep"] == {
        "bar_index": cast(int, signal.metadata["bar_index"]) - 4,
        "bars_ago": 4,
        "level": "swing high",
        "price": 101.0,
    }
    assert run_tape(CisdSweep, tape).signals == []  # no 5/5 pivot, no other level taken


def test_session_and_previous_day_levels_are_not_sweeps_for_the_scanner() -> None:
    # a quiet tape: the 01:00 bar takes the Asia high (100.15) — a sweep for the main
    # model only; the run and CISD follow
    rows: list[Row] = [
        (100.1, 100.5, 99.85, 100.0),  # 01:00 takes the Asia high
        *BEAR_SETUP[8:],  # 01:05 run, 01:10 high 100.8, 01:15 CISD
    ]
    tape = Tape(ny(DAY - timedelta(days=1), "18:00")).at(ny(DAY, "01:00"), *rows)
    tape.quiet(20, level=99.6)
    main = [s for s in run_tape(CisdSweep, tape).signals if s.signal.is_entry]
    assert len(main) == 1
    assert cast(dict[str, Any], main[0].metadata["sweep"])["levels"] == [
        {"level": "Asia high", "price": 100.15}
    ]
    assert scanner(with_slots(tape.bars())).signals == []


def test_the_scanner_uses_the_d7_limit_expiry_tp1_cancel_and_targets() -> None:
    # unfilled: the bars after the CISD stay at 89.6, the limit expires after 12 bars
    expired = scanner(aplus_tape())
    assert [s.signal for s in expired.signals] == [SHORT]
    assert expired.signals[0].expires_after_bars == 12
    assert [e.kind for e in expired.events] == [PositionEventKind.ORDER_EXPIRED]
    # filled at 90.00 on the next bar, TP2 88.40 two bars later; TP1-only: 89.20
    filled = scanner(aplus_tape(after=FILL_AND_TARGET))
    assert [(e.kind, e.price) for e in filled.events] == [
        (PositionEventKind.OPENED, Decimal("90.00")),
        (PositionEventKind.CLOSED, Decimal("88.40")),
    ]
    tp1 = scanner(aplus_tape(after=FILL_AND_TARGET), {"target": "tp1"})
    assert tp1.events[-1].price == Decimal("89.20")
    # TP1 trades before the fill: the order is cancelled on that bar
    cancelled = scanner(aplus_tape(after=TP1_FIRST))
    assert [s.signal for s in cancelled.signals] == [SHORT, SignalAction.EXIT_SHORT]
    assert cancelled.signals[1].metadata["detail"] == "TP1 traded before the fill"
    assert cancelled.events == []


# ── meta, params, determinism ─────────────────────────────────────────────────────────
def test_definition_runs_on_5m_with_the_three_higher_slots() -> None:
    meta = definition_from_class(CisdScanner).meta
    assert meta.timeframes == ("5m",)
    assert meta.context_timeframes == ("15m", "1h", "4h")
    assert meta.on_opposite_signal == "reverse" and meta.skip_entry_beyond_levels is True
    assert meta.warmup_bars == 36


def test_params_follow_the_pine_inputs_and_validate() -> None:
    p = CisdScannerParams()
    assert (p.aplus_only, p.on2, p.on3, p.on4) == (False, True, True, True)
    assert (p.req_sweep, p.sweep_look, p.min_body, p.tp1_r, p.tp2_r) == (True, 12, 0.3, 1.0, 2.0)
    assert (p.entry, p.target, p.limit_expiry_bars, p.cancel_on_tp1) == ("limit", "tp2", 12, True)
    for bad in ({"aplus_only": "maybe"}, {"pv_l": 3}, {"target": "tp3"}, {"sweep_look": 0}):
        with pytest.raises(ValidationError):
            CisdScannerParams.model_validate(bad)


def test_two_runs_give_identical_signals() -> None:
    bars = aplus_tape()
    assert dumps(scanner(bars)) == dumps(scanner(bars))

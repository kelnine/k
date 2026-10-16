"""Long synthetic runs: the engine never takes a step the script cannot take.

Synthetic random walks with volume that rises with the bar's range produce many climaxes
and short-lived campaigns (most die in Phase A or B, as on real charts). Over every bar:
a campaign only changes phase along the script's paths, is only replaced through a reset
or a new climax, enters at most once and in the direction of its outcome, and the reset
counters agree with the ends reported. The strategy on the same bars never faults and
only ever exits the campaign its trade came from.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kterminal.domain.timeframes import Timeframe
from kterminal.marketdata.synthetic import synthetic_bars
from kterminal.strategies.wyckoff_auto import WyckoffAuto
from kterminal.strategies.wyckoff_auto.state import RESET_NAMES, bit_names
from kterminal.strategies.wyckoff_auto.wyckoff_engine import RESEED, Strictness
from tests.unit.strategies.pine_port_support import real_catalog, run
from tests.unit.strategies.wyckoff_auto.scenario import (
    Row,
    Tape,
    Trace,
    accumulation,
    demoted_then_tested_again,
    phase_c_goes_stale_then_new_climax,
    phase_c_quietly_invalidated,
    phase_d_demoted,
    phase_e_fails,
    phase_e_replaced,
    provisional_spring,
    run_engine,
    terminal_test,
)

# phase changes of one campaign within one bar (demotion is D → B, adoption B → D)
MOVES = {("A", "B"), ("B", "C"), ("B", "D"), ("C", "D"), ("D", "B"), ("D", "E"), ("D", "C")}
TRIGGER_BITS = {"Test", "C-Test", "SOS", "SOW", "LPS", "LPSY"}


def rows_of(symbol: str, timeframe: str, seed: int, count: int) -> list[Row]:
    instrument = real_catalog().instrument(symbol)
    bars = synthetic_bars(
        symbol,
        start=datetime(2026, 1, 5, tzinfo=UTC),
        count=count,
        start_price=Decimal(2_000),
        tick_size=instrument.tick_size,
        timeframe=Timeframe.parse(timeframe),
        seed=seed,
        volatility=0.003,
        regime_change_probability=0.02,
    )
    rows: list[Row] = []
    for b in bars:
        spread = float(b.high - b.low) / float(b.close)
        volume = round(float(b.volume) * (1 + 3 * min(spread / 0.004, 3.0)))
        rows.append((float(b.open), float(b.high), float(b.low), float(b.close), volume))
    return rows


def check(trace: Trace) -> dict[str, int]:
    kinds: dict[str, int] = {}
    entered: set[int] = set()
    for i in range(1, len(trace.steps)):
        step, before, after = trace.steps[i], trace.after[i - 1], trace.after[i]
        names = bit_names(step.sig)
        for end in step.ends:
            kinds[end.kind] = kinds.get(end.kind, 0) + 1
        ended = {e.serial for e in step.ends if e.kind != "RS_DEMOTE"}
        if after.serial != before.serial:
            # replaced: a reset or a reseed of the old campaign, or a seed into an empty slot
            assert before.serial in ended or (before.phase == "-" and step.seeded), i
            if step.seeded:
                assert after.phase == "A" and after.stop_side == step.seeded
            else:
                assert after.phase == "-"
        elif after.phase != before.phase:
            assert (before.phase, after.phase) in MOVES, (i, before.phase, after.phase)
            if (before.phase, after.phase) == ("B", "D"):
                assert {"Spring", "SOS"} <= set(names) or {"UTAD", "SOW"} <= set(names), i
            if before.phase == "D" and after.phase in ("B", "C"):
                assert any(e.kind == "RS_DEMOTE" for e in step.ends), i
        check_ = step.entry_check
        if check_ is not None and check_.taken:
            assert after.serial not in entered, i  # one entry per campaign
            entered.add(after.serial)
            assert check_.direction == after.outcome != 0
            assert TRIGGER_BITS & set(names), (i, names)
            assert check_.quality
    engine = trace.engine
    assert engine is not None
    for code, name in RESET_NAMES.items():
        assert engine.rs_counts[code] == kinds.get(name, 0), name
    kinds["entries"] = len(entered)
    kinds["seeds"] = sum(1 for s in trace.steps if s.seeded)
    return kinds


CASES = [
    ("XAUUSD", "15m", 1),
    ("XAUUSD", "15m", 5),
    ("BTCUSD", "5m", 2),
    ("EURUSD", "1h", 3),
    ("NAS100", "5m", 4),
    ("SOLUSD", "15m", 6),
]


@pytest.mark.parametrize(("symbol", "timeframe", "seed"), CASES)
@pytest.mark.parametrize("strictness", ["Conservative", "Standard", "Aggressive"])
def test_the_engine_only_takes_the_scripts_paths(
    symbol: str, timeframe: str, seed: int, strictness: Strictness
) -> None:
    trace = run_engine(
        rows_of(symbol, timeframe, seed, 4_000),
        strictness=strictness,
        mintick=float(real_catalog().instrument(symbol).tick_size),
    )
    kinds = check(trace)
    assert kinds["seeds"] >= 10  # the runs are not vacuous
    assert sum(v for k, v in kinds.items() if k.startswith("RS_") or k == RESEED) >= 10


@pytest.mark.parametrize(("symbol", "timeframe", "seed"), CASES[:4])
def test_the_strategy_only_exits_its_own_campaign(symbol: str, timeframe: str, seed: int) -> None:
    instrument = real_catalog().instrument(symbol)
    bars = list(
        synthetic_bars(
            symbol,
            start=datetime(2026, 1, 5, tzinfo=UTC),
            count=4_000,
            start_price=Decimal(2_000),
            tick_size=instrument.tick_size,
            timeframe=Timeframe.parse(timeframe),
            seed=seed,
            volatility=0.003,
            regime_change_probability=0.02,
        )
    )
    rows = rows_of(symbol, timeframe, seed, 4_000)
    bars = [replace(b, volume=Decimal(int(row[4]))) for b, row in zip(bars, rows, strict=True)]
    result = run(
        WyckoffAuto,
        bars,
        params={"entry_strictness": "Aggressive"},
        instrument=instrument,
        timeframe=timeframe,
    )
    assert result.fault is None and result.rejected == []
    campaign = None
    for signal in result.signals:
        if signal.signal.is_entry:
            meta = signal.metadata["campaign"]
            assert isinstance(meta, dict)
            campaign = meta["serial"]
        elif signal.signal.value == "FLATTEN":
            assert signal.metadata["campaign_serial"] == campaign


def stitched() -> Tape:
    """The targeted scenarios back to back, accumulations and mirrored distributions in
    turn, each shifted to open at the previous close: complete campaigns, entries and
    every exit, with the context of the campaign before each one."""
    parts = [
        accumulation(),
        phase_d_demoted().mirrored(),
        terminal_test(),
        provisional_spring().mirrored(),
        phase_e_fails(),
        phase_c_goes_stale_then_new_climax().mirrored(),
        demoted_then_tested_again(),
        phase_e_replaced().mirrored(),
        phase_c_quietly_invalidated(),
    ]
    out = Tape(parts[0].rows[0][0])
    for part in parts:
        shift = round(out.close - part.rows[0][0], 6) if out.rows else 0.0
        for o, h, low, c, v in part.rows:
            out.bar(
                round(o + shift, 6),
                round(h + shift, 6),
                round(low + shift, 6),
                round(c + shift, 6),
                v,
            )
    return out


@pytest.mark.parametrize(
    ("strictness", "entries"), [("Conservative", 1), ("Standard", 5), ("Aggressive", 5)]
)
def test_stitched_campaigns_take_only_the_scripts_paths(
    strictness: Strictness, entries: int
) -> None:
    tape = stitched()
    assert min(row[2] for row in tape.rows) > 0
    kinds = check(run_engine(tape, strictness=strictness))
    assert kinds["entries"] >= entries, kinds
    assert {"RS_EEND", "RS_DEMOTE", "RS_INVALID", "RESEED", "RS_STALE"} <= set(kinds), kinds


@pytest.mark.parametrize("strictness", ["Conservative", "Standard", "Aggressive"])
def test_stitched_trades_are_exited_by_their_own_campaign(strictness: str) -> None:
    result = run(
        WyckoffAuto, stitched().bars(), params={"entry_strictness": strictness}, timeframe="15m"
    )
    assert result.fault is None and result.rejected == []
    campaign = None
    flattens = 0
    for signal in result.signals:
        if signal.signal.is_entry:
            meta = signal.metadata["campaign"]
            assert isinstance(meta, dict)
            campaign = meta["serial"]
        elif signal.signal.value == "FLATTEN":
            assert signal.metadata["campaign_serial"] == campaign
            flattens += 1
    assert flattens >= 1

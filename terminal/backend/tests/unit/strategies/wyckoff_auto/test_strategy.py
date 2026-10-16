"""The strategy through the real runner: the Auto entry as a market order with the D5 stop
(and the 2R variant's target), the structure exits of the trade's own campaign, and the
doc 13 decisions D3 (gap guard, wrong-side stop) and D4 (ignore while in a trade)."""

import math
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from kterminal.core.enums import Direction, SignalAction
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.strategies.wyckoff_auto import WyckoffAuto
from kterminal.strategies.wyckoff_auto import strategy as strategy_module
from kterminal.strategy_engine import CloseReason, PositionEventKind, SignalOutput
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import T0, XAUUSD
from tests.unit.strategies.pine_port_support import (
    actions,
    dumps,
    of_kind,
    run,
    strategy_object,
)
from tests.unit.strategies.wyckoff_auto.scenario import (
    ADOPTED,
    DEMOTED,
    E_FAILED,
    E_TIMEOUT,
    LPS,
    NEW_CLIMAX,
    QUIET_INVALID,
    RESEEDED,
    SPRING_LOW,
    STALE_C,
    TEST,
    Tape,
    accumulation,
    demoted_then_tested_again,
    distribution,
    phase_c_goes_stale_then_new_climax,
    phase_c_invalidated,
    phase_c_quietly_invalidated,
    phase_d_demoted,
    phase_e_fails,
    phase_e_replaced,
    phase_e_times_out,
    provisional_spring,
    run_engine,
)

TF = "15m"
ENTRY = TEST + 4  # 318: the Spring's Test is confirmed
LONG, SHORT, FLATTEN = SignalAction.LONG, SignalAction.SHORT, SignalAction.FLATTEN


def go(tape: Tape, **params: Any) -> StrategyTestResult:
    result = run(WyckoffAuto, tape.bars(), params=params or None, timeframe=TF)
    assert result.fault is None and result.rejected == [], (result.fault, result.rejected)
    return result


def acts(result: StrategyTestResult) -> list[tuple[int, SignalAction]]:
    return actions(result, timeframe=TF)


def atr_at(tape: Tape, bar: int) -> float:
    return run_engine(tape.rows[: bar + 1]).steps[bar].m.a


def tick(x: float) -> Decimal:
    return XAUUSD.round_price(Decimal(repr(x)))


# ── entries ───────────────────────────────────────────────────────────────────────────────
def test_standard_enters_long_on_the_test_with_the_stop_under_the_spring() -> None:
    tape = accumulation()
    result = go(tape)
    assert acts(result)[0] == (ENTRY, LONG)
    entry = result.signals[0]
    stop = SPRING_LOW - 0.5 * atr_at(tape, ENTRY)  # D5: hard level - 0.5 ATR(14)
    assert entry.entry == Decimal("121.90")  # the close of the qualifying bar (L1746)
    assert entry.stop_loss == tick(stop) and entry.take_profit is None
    meta = entry.metadata
    assert meta["trigger"] == "Wyckoff: long entry"
    assert meta["pine_signal"] == "standardTestTrig"
    assert meta["entry_kind"] == "TEST" and meta["events"] == ["Test"]
    assert meta["hard_level"] == SPRING_LOW and meta["stop_basis"] == "spring"
    assert meta["script_stop"] == pytest.approx(stop)
    assert (meta["confidence"], meta["validation"], meta["readiness"]) == (65, 95, 7)
    campaign = meta["campaign"]
    assert isinstance(campaign, dict)
    assert campaign["phase"] == "C" and campaign["outcome"] == "ACCUM"
    assert campaign["type"] == "Accumulation" and campaign["spring_utad_price"] == SPRING_LOW
    assert meta["effort"] == "volume"
    # a market order: filled at the next bar's open (doc 13 D3)
    opened = of_kind(result, PositionEventKind.OPENED)
    assert len(opened) == 1 and opened[0].time == T0 + (ENTRY + 1) * timedelta(minutes=15)
    assert opened[0].direction is Direction.LONG


def test_a_distribution_enters_short_above_the_utad() -> None:
    tape = distribution()
    result = go(tape)
    assert acts(result)[0] == (ENTRY, SHORT)
    utad = 600 - SPRING_LOW
    entry = result.signals[0]
    assert entry.stop_loss == tick(utad + 0.5 * atr_at(tape, ENTRY))
    assert entry.metadata["trigger"] == "Wyckoff: short entry"
    assert entry.metadata["stop_basis"] == "utad"


@pytest.mark.parametrize(
    ("strictness", "bar", "kind"),
    [("Conservative", LPS + 4, "LPS"), ("Aggressive", ENTRY, "TEST")],
)
def test_the_strictness_variants(strictness: str, bar: int, kind: str) -> None:
    result = go(accumulation(), entry_strictness=strictness)
    assert [a for a in acts(result) if a[1] is LONG] == [(bar, LONG)]
    assert result.signals[0].metadata["entry_kind"] == kind


def test_aggressive_enters_on_an_adopted_spring_with_the_spring_as_the_stop() -> None:
    tape = provisional_spring()
    result = go(tape, entry_strictness="Aggressive")
    assert acts(result) == [(ADOPTED, LONG)]
    meta = result.signals[0].metadata
    assert meta["pine_signal"] == "aggressiveStrengthFallback" and meta["entry_kind"] == "STRENGTH"
    assert meta["events"] == ["Spring", "SOS"]
    assert meta["hard_level"] == 119.4  # the adopted provisional Spring (f_adoptProv)
    assert go(tape).signals == []  # Standard has no SOS trigger


def test_the_2r_variant_adds_a_fixed_target() -> None:
    tape = accumulation()
    result = go(tape, target="2R")
    entry = result.signals[0]
    stop = SPRING_LOW - 0.5 * atr_at(tape, ENTRY)
    assert entry.take_profit == tick(121.9 + 2.0 * (121.9 - stop))
    assert entry.metadata["target_mode"] == "2R"


def test_the_stop_buffer_is_a_parameter() -> None:
    tape = accumulation()
    entry = go(tape, stop_atr=1.0).signals[0]
    assert entry.stop_loss == tick(SPRING_LOW - 1.0 * atr_at(tape, ENTRY))


# ── D5 exits: the campaign's own structure events ────────────────────────────────────────
EXITS = [
    (phase_c_quietly_invalidated, QUIET_INVALID, "INVALIDATION", "RS_INVALID"),
    (phase_d_demoted, DEMOTED, "DEMOTION", "RS_DEMOTE"),
    (phase_e_fails, E_FAILED, "PHASE_E_FAILURE", "RS_EEND"),
    (phase_e_times_out, E_TIMEOUT, "PHASE_E_TIMEOUT", "RS_EEND"),
    (phase_e_replaced, RESEEDED, "REPLACED_BY_CLIMAX", "RESEED"),
]


@pytest.mark.parametrize(("build", "bar", "event", "pine_event"), EXITS, ids=[e[2] for e in EXITS])
def test_each_structure_event_flattens_the_trade(
    build: Any, bar: int, event: str, pine_event: str
) -> None:
    tape: Tape = build()
    tape.step(tape.close)  # one more bar: the flatten fills at its open
    result = go(tape)
    assert acts(result) == [(ENTRY, LONG), (bar, FLATTEN)]
    flatten = result.signals[1]
    meta = flatten.metadata
    assert meta["exit_event"] == event and meta["pine_event"] == pine_event
    assert meta["campaign_serial"] == result.signals[0].metadata["campaign"]["serial"]  # type: ignore[index]
    assert meta["entry_bar_index"] == ENTRY and meta["trade_direction"] == "long"
    assert flatten.reason is not None and flatten.reason.startswith("Wyckoff: ")
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert len(closed) == 1
    assert closed[0].reason is CloseReason.SIGNAL_EXIT  # a structure exit, not a time exit
    assert closed[0].time == T0 + (bar + 1) * timedelta(minutes=15)
    assert result.ignored == []


def test_the_exit_metadata_carries_the_values_that_decided_it() -> None:
    tape = phase_e_fails()
    meta = go(tape).signals[1].metadata
    values = meta["values"]
    assert isinstance(values, dict)
    assert values["e_fail"] is True and values["range_mid"] == pytest.approx(122.2125)
    assert meta["campaign_phase"] == "E" and meta["campaign_outcome"] == "ACCUM"


def test_a_stop_hit_ends_the_trade_and_its_campaign_events_send_nothing() -> None:
    """phase_c_invalidated: the collapse hits the stop at 322, a bar before the campaign
    is invalidated (323); the trade is over, so there is nothing to flatten."""
    result = go(phase_c_invalidated())
    assert acts(result) == [(ENTRY, LONG)]
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert len(closed) == 1 and closed[0].reason is CloseReason.STOP_LOSS
    assert run_engine(phase_c_invalidated()).ends("RS_INVALID") == [ENTRY + 5]


def test_a_stale_campaign_keeps_its_trade_until_a_new_climax_takes_its_place() -> None:
    """RS_STALE is not one of the D5 exits: the trade keeps its stop; the next climax
    (here a BC at 419) replaces the campaign the trade came from."""
    tape = phase_c_goes_stale_then_new_climax()
    result = go(tape)
    assert acts(result) == [(ENTRY, LONG), (NEW_CLIMAX, FLATTEN)]
    meta = result.signals[1].metadata
    assert meta["exit_event"] == "REPLACED_BY_CLIMAX" and meta["campaign_went_stale"] is True
    new_climax = meta["new_climax"]
    assert isinstance(new_climax, dict) and new_climax["side"] == "BC"
    assert new_climax["serial"] != meta["campaign_serial"]
    assert meta["pine_event"] == "RESEED" and meta["campaign_phase"] is None
    assert run_engine(tape).ends("RS_STALE") == [STALE_C]


def test_a_demoted_campaign_does_not_trade_again() -> None:
    """After the demotion exit, the campaign's new Spring and Test (343) bring no entry:
    entryTime survived the demotion (the spec's 'no re-entry after demotion')."""
    result = go(demoted_then_tested_again())
    assert acts(result) == [(ENTRY, LONG), (DEMOTED, FLATTEN)]


# ── doc 13 D3 ─────────────────────────────────────────────────────────────────────────────
def test_d3_the_entry_is_skipped_when_the_next_open_is_past_the_stop() -> None:
    tape = accumulation("test")  # through 318
    tape.bar(118.5, 119.0, 118.4, 118.9)  # 319 opens under the 118.80 stop
    tape.path([119.3, 119.7])
    result = go(tape)
    assert acts(result) == [(ENTRY, LONG)]
    cancelled = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert len(cancelled) == 1 and cancelled[0].detail == "OPEN_BEYOND_STOP"
    assert of_kind(result, PositionEventKind.OPENED) == []
    assert strategy_object(result)._trade is None


@pytest.mark.parametrize(("level", "code"), [(122.5, "STOP_WRONG_SIDE"), (math.nan, "LEVELS_NA")])
def test_d3_no_trade_when_the_stop_is_not_below_the_close(
    monkeypatch: pytest.MonkeyPatch, level: float, code: str
) -> None:
    monkeypatch.setattr(strategy_module, "hard_level", lambda s, side: level)
    result = go(accumulation("test"))
    assert acts(result) == [(ENTRY, SignalAction.NO_TRADE)]
    no_trade = result.signals[0]
    assert no_trade.reason == code and no_trade.persist
    assert no_trade.metadata["pine_signal"] == "standardTestTrig"


# ── doc 13 D4 ─────────────────────────────────────────────────────────────────────────────
class _Twice(WyckoffAuto):
    """Repeats each entry on the next bar, once as is and once reversed: a new signal
    while the trade is open."""

    def on_start(self) -> None:
        super().on_start()
        self._last: Signal | None = None

    def on_bar(self, bar: Bar) -> SignalOutput:
        out = super().on_bar(bar)
        own = list(out) if isinstance(out, list) else []
        extra: list[Signal] = []
        last = self._last
        if last is not None:
            stop = last.stop_loss
            assert stop is not None and last.entry is not None
            extra.append(self.ctx.long(stop_loss=stop))
            extra.append(self.ctx.short(stop_loss=last.entry + (last.entry - stop)))
            self._last = None
        for signal in own:
            if signal.signal is LONG:
                self._last = signal
        return [*own, *extra]


def test_d4_new_entries_are_ignored_while_in_a_trade() -> None:
    result = run(_Twice, accumulation("sos").bars(), timeframe=TF)
    assert result.fault is None
    reasons = sorted(reason for _, reason in result.ignored)
    assert reasons == ["OPPOSITE_POSITION_OPEN", "POSITION_EXISTS"]
    assert len(of_kind(result, PositionEventKind.OPENED)) == 1
    assert of_kind(result, PositionEventKind.CLOSED) == []
    assert WyckoffAuto.meta.on_opposite_signal == "ignore"
    assert WyckoffAuto.meta.skip_entry_beyond_levels is True


# ── determinism, time gaps, warm-up ───────────────────────────────────────────────────────
def test_two_runs_give_identical_signals() -> None:
    tape = phase_e_replaced()
    assert dumps(go(tape)) == dumps(go(tape))
    first = go(tape, entry_strictness="Conservative", target="2R")
    second = go(tape, entry_strictness="Conservative", target="2R")
    assert dumps(first) == dumps(second) and first.signals


def test_a_weekend_gap_does_not_change_the_decisions() -> None:
    """The engine counts bars, not clock time; the only clock-based heuristic (readiness
    age, L961) is 0 on an entry bar. A two-day gap in the middle of Phase B changes no
    decision bar."""
    tape = phase_e_fails()
    bars = tape.bars()
    gap = timedelta(days=2)
    shifted = [b if i < 300 else _moved(b, gap) for i, b in enumerate(bars)]
    plain = go(tape)
    gapped = run(WyckoffAuto, shifted, timeframe=TF)
    assert gapped.fault is None
    index = {b.open_time: i for i, b in enumerate(shifted)}
    assert [(index[s.bar_time], s.signal) for s in gapped.signals if s.bar_time] == acts(plain)


def test_signals_are_discarded_in_warm_up_and_a_warm_up_trade_has_no_exit() -> None:
    """Warm-up replays the engine (the campaign uses its entry there, as on TradingView's
    history) but no trade is taken, so its later Phase E failure sends no exit."""
    bars = phase_e_fails().bars()
    result = run(WyckoffAuto, bars[ENTRY + 1 :], warmup_bars=bars[: ENTRY + 1], timeframe=TF)
    assert result.fault is None and result.signals == []


def _moved(bar: Bar, by: timedelta) -> Bar:
    return Bar.of(
        bar.instrument,
        bar.timeframe,
        bar.open_time + by,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        bar.volume,
    )

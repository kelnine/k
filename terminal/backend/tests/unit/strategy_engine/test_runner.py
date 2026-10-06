from decimal import Decimal

from kterminal.core.enums import SignalAction
from kterminal.domain.timeframes import H1, M1, M5
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategy_engine.model import PositionEventKind
from kterminal.strategy_engine.testing import run_strategy
from tests.fixtures.instruments import XAUUSD, bars, gold_minutes
from tests.fixtures.strategies import ContextProbe, Crasher, Misbehaving, Scripted, SmaCross

FLAT = [(100.0, 101.0, 99.0, 100.0)] * 10


def test_signals_are_stamped_with_identity_and_rounded() -> None:
    result = run_strategy(
        Scripted,
        instrument=XAUUSD,
        bars=bars("XAUUSD", "5m", FLAT),
        timeframe="5m",
        params={"long_on": [2], "stop_distance": "1.234"},
        instance_id="scripted_a",
    )
    (signal,) = result.signals
    assert signal.strategy_id == "scripted_a"
    assert signal.symbol == "XAUUSD"
    assert signal.timeframe == "5m"
    assert signal.strategy_version == result.runner.resolved.version  # type: ignore[union-attr]
    assert signal.stop_loss == Decimal("98.77")  # rounded to the 0.01 tick
    assert signal.timestamp == bars("XAUUSD", "5m", FLAT)[1].close_time
    assert signal.bar_time == bars("XAUUSD", "5m", FLAT)[1].open_time
    assert [e.kind for e in result.events] == [PositionEventKind.OPENED]


def test_invalid_outputs_are_rejected_not_routed() -> None:
    result = run_strategy(
        Misbehaving, instrument=XAUUSD, bars=bars("XAUUSD", "5m", FLAT[:1]), timeframe="5m"
    )
    assert len(result.signals) == 1
    codes = sorted(r.code for r in result.rejected)
    assert codes == ["IDENTITY_MISMATCH", "NOT_A_SIGNAL", "STOP_WRONG_SIDE"]
    assert result.fault is None


def test_exception_faults_the_instance_and_stops_signals() -> None:
    result = run_strategy(
        Crasher,
        instrument=XAUUSD,
        bars=bars("XAUUSD", "5m", FLAT),
        timeframe="5m",
        params={"crash_on": 3},
    )
    assert result.fault is not None
    assert result.fault.error_type == "ZeroDivisionError"
    assert result.fault.stage == "on_bar"
    assert "strategy bug" in result.fault.traceback
    assert [s.signal for s in result.signals] == [SignalAction.LONG]  # nothing after the fault
    assert result.runner is not None and result.runner.bars_evaluated == 3


def test_warmup_primes_state_but_emits_nothing() -> None:
    history = bars("XAUUSD", "5m", FLAT[:5])
    live = bars("XAUUSD", "5m", FLAT[:3], start=history[-1].close_time)
    result = run_strategy(
        Scripted,
        instrument=XAUUSD,
        bars=live,
        timeframe="5m",
        params={"long_on": [2, 6]},
        warmup_bars=history,
    )
    # bar 2 happened during warm-up → discarded; bar 6 is the first live bar
    assert len(result.signals) == 1
    assert result.signals[0].timestamp == live[0].close_time


def test_context_timeframe_has_no_look_ahead() -> None:
    minutes = gold_minutes(180)
    stream = [
        bar
        for batch in aggregate_stream(minutes, M1, [M5, H1])
        for bar in batch
        if bar.timeframe in (M5, H1)
    ]
    result = run_strategy(ContextProbe, instrument=XAUUSD, bars=stream, timeframe="5m")
    assert result.fault is None
    probe = result.runner._strategy  # type: ignore[union-attr]
    seen = probe.seen  # type: ignore[union-attr]
    assert len(seen) == 36
    # at 01:00 the first hourly bar has just closed and is visible; before that none is
    by_time = {t: (n, latest) for t, n, latest in seen}
    assert by_time["2026-01-05T00:55:00+00:00"] == (0, None)
    assert by_time["2026-01-05T01:00:00+00:00"] == (1, "2026-01-05T01:00:00+00:00")
    assert by_time["2026-01-05T01:55:00+00:00"][0] == 1


def test_sma_strategy_is_deterministic() -> None:
    minutes = gold_minutes(2_000, seed=11)
    five = [b for batch in aggregate_stream(minutes, M1, [M5]) for b in batch if b.timeframe == M5]
    first = run_strategy(SmaCross, instrument=XAUUSD, bars=five, timeframe="5m")
    second = run_strategy(SmaCross, instrument=XAUUSD, bars=five, timeframe="5m")
    assert first.signals == second.signals
    assert len(first.signals) > 2

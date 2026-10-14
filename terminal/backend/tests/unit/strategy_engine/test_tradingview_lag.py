"""TradingView-compatible higher-timeframe access, the lagged series view and bar_index."""

from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta

import pytest

from kterminal.core.registry import Registry
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import H1, M1, M5, M15, Timeframe
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategy_engine import BarSeries
from kterminal.strategy_engine.context import StrategyContext
from kterminal.strategy_engine.instances import InstanceSpec, resolve_instance
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from kterminal.strategy_engine.runner import StrategyRunner
from tests.fixtures.engine_strategies import Idle
from tests.fixtures.instruments import INSTRUMENTS, T0, XAUUSD, bars, gold_minutes


def runner_for(
    timeframe: str, context: Sequence[str] = (), *, max_bars: int = 5_000
) -> StrategyRunner:
    registry: Registry[StrategyDefinition] = Registry("strategy definition")
    definition = definition_from_class(Idle)
    registry.register(definition.id, definition)
    spec = InstanceSpec(
        id="idle_a",
        strategy="idle",
        instruments=("XAUUSD",),
        timeframe=timeframe,
        context_timeframes=tuple(context),
    )
    resolved = resolve_instance(spec, instruments=INSTRUMENTS, definitions=registry)
    runner = StrategyRunner(resolved, XAUUSD, max_bars=max_bars)
    assert runner.start() is None
    return runner


def evaluated(
    runner: StrategyRunner, minutes: list[Bar], targets: list[Timeframe]
) -> Iterator[tuple[StrategyContext, list[Bar]]]:
    """Feed the aggregated stream; yield the context after every primary bar, together
    with every bar of the context timeframes built so far."""
    built: list[Bar] = []
    for batch in aggregate_stream(minutes, M1, targets):
        built.extend(b for b in batch if b.timeframe != runner.resolved.timeframe)
        if runner.process(batch) is not None:
            yield runner.ctx, built


def closes(series: Sequence[Bar]) -> list[datetime]:
    return [b.close_time for b in series]


def test_a_15m_bar_reaches_a_1m_strategy_one_bar_later_with_tradingview_lag() -> None:
    runner = runner_for("1m", ["15m"])
    seen = {}
    for ctx, built in evaluated(runner, gold_minutes(60), [M15]):
        lab = ctx.series("15m")
        tv = ctx.series("15m", tradingview_lag=True)
        fifteen = [b for b in built if b.timeframe == M15]
        # the lab: closed by the evaluated bar's close; TradingView: by its open
        assert closes(lab.last(len(lab))) == [
            b.close_time for b in fifteen if b.close_time <= ctx.bar.close_time
        ]
        assert closes(tv.last(len(tv))) == [
            b.close_time for b in fifteen if b.close_time <= ctx.bar.open_time
        ]
        seen[ctx.bar.open_time - T0] = (len(lab), len(tv))
    minute = timedelta(minutes=1)
    assert seen[14 * minute] == (1, 0)  # the 00:14 bar closes with the first 15m bar
    assert seen[15 * minute] == (1, 1)  # … TradingView shows it from the 00:15 bar on
    assert seen[29 * minute] == (2, 1)
    assert seen[30 * minute] == (2, 2)


def test_an_hourly_bar_reaches_a_5m_strategy_one_bar_later_with_tradingview_lag() -> None:
    runner = runner_for("5m", ["1h"])
    by_open = {}
    for ctx, _built in evaluated(runner, gold_minutes(180), [M5, H1]):
        tv = ctx.series("1h", tradingview_lag=True)
        latest = tv.latest
        assert latest is None or latest.close_time <= ctx.bar.open_time
        by_open[ctx.bar.open_time - T0] = (len(ctx.series("1h")), len(tv), tv.hidden)
    assert by_open[timedelta(minutes=55)] == (1, 0, 1)  # 00:55-01:00: the lab sees 00:00-01:00
    assert by_open[timedelta(hours=1)] == (1, 1, 0)  # TradingView from the 01:00 bar
    assert by_open[timedelta(hours=1, minutes=55)] == (2, 1, 1)


def test_after_a_data_gap_the_closed_bar_is_visible_on_the_next_bar() -> None:
    gap = (T0 + timedelta(hours=1), T0 + timedelta(hours=1, minutes=10))
    minutes = [b for b in gold_minutes(150) if not gap[0] <= b.open_time < gap[1]]
    runner = runner_for("5m", ["1h"])
    seen = {
        ctx.bar.open_time - T0: len(ctx.series("1h", tradingview_lag=True))
        for ctx, _ in evaluated(runner, minutes, [M5, H1])
    }
    assert timedelta(hours=1) not in seen and timedelta(hours=1, minutes=5) not in seen
    assert seen[timedelta(minutes=55)] == 0
    assert seen[timedelta(hours=1, minutes=10)] == 1  # the first bar after the gap


def test_lag_on_the_primary_series_hides_the_evaluated_bar_and_lower_timeframes_refuse() -> None:
    runner = runner_for("5m", ["1m"])
    contexts = list(evaluated(runner, gold_minutes(30), [M5]))
    ctx = contexts[-1][0]
    own = ctx.series("5m", tradingview_lag=True)
    assert len(own) == len(ctx.bars) - 1 and own.latest == ctx.bars.bar(-2)  # like close[1]
    with pytest.raises(ValueError, match="primary timeframe 5m or higher"):
        ctx.series("1m", tradingview_lag=True)
    with pytest.raises(KeyError, match="not declared"):
        ctx.series("15m", tradingview_lag=True)


def test_the_series_view_has_the_read_api_of_a_series() -> None:
    series = BarSeries("XAUUSD", M5)
    rows = [(100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i) for i in range(4)]
    for bar in bars("XAUUSD", "5m", rows):
        series._append(bar)
    view = series.closed_by(series.bar(-2).open_time)  # the last two have not closed
    assert view.hidden == 2 and len(view) == 2
    assert list(view.close) == [100.5, 101.5] and list(view.high) == [101.0, 102.0]
    assert list(view.open) == [100.0, 101.0] and list(view.low) == [99.0, 100.0]
    assert len(view.volume) == 2 and len(view.open_times) == 2
    assert not view.close.flags.writeable and not view.open_times.flags.writeable
    assert view.bar(-1) == series.bar(1) and view.bar(0) == series.bar(0)
    assert view.latest == series.bar(1)
    assert list(view.last(5)) == [series.bar(0), series.bar(1)]
    assert list(view.last(1)) == [series.bar(1)] and view.last(0) == ()
    with pytest.raises(IndexError):
        view.bar(2)
    with pytest.raises(IndexError):
        view.bar(-3)
    with pytest.raises(ValueError, match="count"):
        view.last(-1)
    assert repr(view) == "SeriesView(XAUUSD 5m, 2 bars, 2 hidden)"
    everything = series.closed_by(series.bar(-1).close_time)
    assert everything.hidden == 0 and len(everything) == 4
    nothing = series.closed_by(series.bar(0).open_time)
    assert len(nothing) == 0 and nothing.latest is None and nothing.last(3) == ()
    assert view.instrument == "XAUUSD" and view.timeframe == M5


def test_bar_index_counts_every_primary_bar_beyond_the_series_cap() -> None:
    runner = runner_for("5m", ["1h"], max_bars=3)
    with pytest.raises(RuntimeError, match="no bar"):
        _ = runner.ctx.bar_index
    indices = [
        (ctx.bar_index, len(ctx.bars)) for ctx, _ in evaluated(runner, gold_minutes(70), [M5, H1])
    ]
    assert [i for i, _ in indices] == list(range(14))  # hourly batches do not count
    assert indices[-1] == (13, 3)  # the series keeps 3 bars, the index keeps counting


def test_periods_need_a_trading_day_rule() -> None:
    runner = runner_for("5m")
    with pytest.raises(KeyError, match="no trading-day rule for XAUUSD"):
        _ = runner.ctx.periods


def test_window_starts_do_not_depend_on_the_series_length() -> None:
    runner = runner_for("5m", max_bars=1)  # the series keeps the evaluated bar only
    starts = [
        ctx.bar.open_time - T0
        for ctx, _ in evaluated(runner, gold_minutes(150), [M5])
        if ctx.session_started("0100-0200", "UTC")
    ]
    assert len(runner.ctx.bars) == 1
    assert starts == [timedelta(hours=1)]

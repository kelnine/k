"""The incremental aggregator yields exactly what aggregate_stream yields."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.domain.market import Bar
from kterminal.domain.timeframes import H1, M1, M5, M15
from kterminal.marketdata.aggregator import StreamAggregator, aggregate_stream
from kterminal.marketdata.synthetic import merge_streams
from tests.fixtures.instruments import T0

MIN = timedelta(minutes=1)


def bar(symbol: str, minute: int) -> Bar:
    price = Decimal(100 + minute % 7)
    return Bar.of(symbol, M1, T0 + minute * MIN, price, price + 1, price - 1, price)


def stream(minutes_a: list[int], minutes_b: list[int]) -> list[Bar]:
    return merge_streams(
        iter([bar("AAA", m) for m in sorted(set(minutes_a))]),
        iter([bar("BBB", m) for m in sorted(set(minutes_b))]),
    )


def by_minute(bars: list[Bar]) -> list[tuple[datetime, list[Bar]]]:
    groups: dict[datetime, list[Bar]] = {}
    for b in bars:
        groups.setdefault(b.open_time, []).append(b)
    return sorted(groups.items())


minutes = st.lists(st.integers(min_value=0, max_value=240), max_size=120)


@given(minutes, minutes)
def test_push_and_finish_equal_aggregate_stream(a: list[int], b: list[int]) -> None:
    bars = stream(a, b)
    expected = list(aggregate_stream(bars, M1, [M5, M15, H1]))
    agg = StreamAggregator(M1, [M5, M15, H1])
    got = [batch for item in bars for batch in agg.push(item)] + agg.finish()
    assert got == expected


@given(minutes, minutes)
def test_advancing_every_minute_only_makes_batches_available_earlier(
    a: list[int], b: list[int]
) -> None:
    """A live feed advances after every minute, with or without bars. As long as a later
    bar does arrive, the batches and their order are those of the offline stream."""
    bars = stream(a, b)
    expected = list(aggregate_stream(bars, M1, [M5, M15, H1]))
    agg = StreamAggregator(M1, [M5, M15, H1])
    got: list[list[Bar]] = []
    groups = dict(by_minute(bars))
    last = bars[-1].open_time if bars else T0
    for minute in range(242):
        at = T0 + minute * MIN
        for item in groups.get(at, []):
            got.extend(agg.push(item))
        if at < last:  # after the last bar only the passing of time could close periods
            ready = agg.advance(at + MIN)
            assert all(batch[0].close_time <= at + MIN for batch in ready)
            got.extend(ready)
    got.extend(agg.finish())
    assert got == expected


def test_a_bar_older_than_the_advance_point_is_refused() -> None:
    agg = StreamAggregator(M1, [M5])
    agg.push(bar("AAA", 0))
    assert agg.advance(T0 + MIN) == [[bar("AAA", 0)]]
    assert agg.advanced_to == T0 + MIN
    with pytest.raises(ValueError, match="after the stream advanced"):
        agg.push(bar("BBB", 0))


def test_a_five_minute_bar_closes_when_its_period_is_over_even_without_its_last_minute() -> None:
    agg = StreamAggregator(M1, [M5])
    for minute in range(4):  # 00:00-00:03; 00:04 never comes (market closed)
        agg.push(bar("AAA", minute))
        agg.advance(T0 + (minute + 1) * MIN)
    assert agg.advance(T0 + 4 * MIN) == []
    (five,) = agg.advance(T0 + 5 * MIN)
    assert [(b.timeframe, b.close_time) for b in five] == [(M5, T0 + 5 * MIN)]

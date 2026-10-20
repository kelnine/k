from datetime import timedelta
from decimal import Decimal

import pytest

from kterminal.domain.timeframes import H1, M1, M5, M15, Timeframe
from kterminal.marketdata.aggregator import BarAggregator, aggregate_stream, batches_by_close
from kterminal.marketdata.synthetic import merge_streams, synthetic_bars
from tests.fixtures.instruments import T0, bars, gold_minutes


def minute_rows(n: int) -> list[tuple[float, float, float, float]]:
    return [(100 + i, 100.5 + i, 99.5 + i, 100.25 + i) for i in range(n)]


def test_five_minute_bar_ohlcv() -> None:
    agg = BarAggregator(M1, [M5])
    out = [agg.add(bar) for bar in bars("XAUUSD", "1m", minute_rows(5))]
    assert [len(o) for o in out] == [1, 1, 1, 1, 2]
    five = out[-1][1]
    assert five.timeframe == M5
    assert (five.open, five.high, five.low, five.close) == (
        Decimal(100),
        Decimal("104.5"),
        Decimal("99.5"),
        Decimal("104.25"),
    )
    assert five.open_time == T0
    assert five.close_time == T0 + timedelta(minutes=5)


def test_higher_timeframes_close_only_when_complete_and_in_order() -> None:
    batches = list(aggregate_stream(bars("XAUUSD", "1m", minute_rows(60)), M1, [M5, M15, H1]))
    assert len(batches) == 60
    last = batches[-1]
    assert [b.timeframe for b in last] == [M1, M5, M15, H1]
    assert all(b.close_time == last[0].close_time for b in last)
    counts = {
        tf: sum(1 for batch in batches for b in batch if b.timeframe == tf) for tf in (M5, M15, H1)
    }
    assert counts == {M5: 12, M15: 4, H1: 1}


def test_gap_closes_period_without_last_base_bar() -> None:
    rows = minute_rows(3)
    first = bars("XAUUSD", "1m", rows)  # 00:00-00:03 then a gap
    later = bars("XAUUSD", "1m", rows[:1], start=T0 + timedelta(minutes=10))
    batches = list(aggregate_stream([*first, *later], M1, [M5]))
    five = [b for batch in batches for b in batch if b.timeframe == M5]
    assert len(five) == 1
    assert five[0].close_time == T0 + timedelta(minutes=5)
    assert five[0].close == first[-1].close
    closes = [batch[0].close_time for batch in batches]
    assert closes == sorted(closes)


def test_instruments_closing_together_share_a_batch() -> None:
    gold = synthetic_bars(
        "XAUUSD", start=T0, count=10, start_price=Decimal(2650), tick_size=Decimal("0.01"), seed=1
    )
    silver = synthetic_bars(
        "XAGUSD", start=T0, count=10, start_price=Decimal(30), tick_size=Decimal("0.001"), seed=2
    )
    batches = list(aggregate_stream(merge_streams(gold, silver), M1, [M5]))
    assert len(batches) == 10
    assert {b.instrument for b in batches[4]} == {"XAUUSD", "XAGUSD"}
    assert len(batches[4]) == 4  # 1m + 5m for both


def test_validation() -> None:
    with pytest.raises(ValueError, match="whole multiple"):
        BarAggregator(Timeframe.parse("2m"), [Timeframe.parse("5m")])
    with pytest.raises(ValueError, match="intraday"):
        BarAggregator(M1, [Timeframe.parse("1D")])
    agg = BarAggregator(M1, [M5])
    b = bars("XAUUSD", "1m", minute_rows(2))
    agg.add(b[1])
    with pytest.raises(ValueError, match="strictly increasing"):
        agg.add(b[0])
    with pytest.raises(ValueError, match="expected 1m"):
        agg.add(bars("XAUUSD", "5m", minute_rows(1))[0])


def test_batches_by_close() -> None:
    stream = bars("XAUUSD", "1m", minute_rows(3))
    assert [len(b) for b in batches_by_close(stream)] == [1, 1, 1]


def test_synthetic_is_deterministic_and_respects_calendar() -> None:
    def gen(seed: int) -> list[object]:
        return list(
            synthetic_bars(
                "XAUUSD",
                start=T0,
                count=50,
                start_price=Decimal(2650),
                tick_size=Decimal("0.01"),
                seed=seed,
            )
        )

    assert gen(5) == gen(5)
    assert gen(5) != gen(6)
    weekdays_only = list(
        synthetic_bars(
            "XAUUSD",
            start=T0 - timedelta(days=2),
            count=10,
            start_price=Decimal(1),
            tick_size=Decimal("0.01"),
            is_open=lambda t: t.weekday() < 5,
        )
    )
    assert all(b.open_time.weekday() < 5 for b in weekdays_only)


def test_a_stream_starting_mid_period_never_emits_that_partial_period() -> None:
    minutes = list(gold_minutes(180))  # 00:00 – 03:00
    late = minutes[97:]  # starts at 01:37, inside the 01:00 hour and the 01:35 five minutes
    hourly = [
        b for batch in aggregate_stream(late, M1, [M5, H1]) for b in batch if b.timeframe == H1
    ]
    fives = [
        b for batch in aggregate_stream(late, M1, [M5, H1]) for b in batch if b.timeframe == M5
    ]
    assert [b.open_time.hour for b in hourly] == [2]  # 01:00 is incomplete: dropped
    assert fives[0].open_time.minute == 40  # 01:35 is incomplete: dropped
    full = {
        (b.timeframe, b.open_time): b
        for batch in aggregate_stream(minutes, M1, [M5, H1])
        for b in batch
    }
    assert all(full[(b.timeframe, b.open_time)] == b for b in [*hourly, *fives])


def test_a_gap_in_one_instrument_never_sends_batches_back_in_time() -> None:
    near = list(
        synthetic_bars(
            "NEARUSD",
            start=T0,
            count=30,
            start_price=Decimal(2),
            tick_size=Decimal("0.0001"),
            seed=1,
        )
    )
    gold = [b for b in gold_minutes(30) if not 8 <= b.open_time.minute < 12]  # feed gap
    closes = [
        batch[0].close_time for batch in aggregate_stream(merge_streams(near, gold), M1, [M5])
    ]
    assert closes == sorted(closes) and len(closes) == len(set(closes))

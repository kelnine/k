"""Previous / current trading day, week and month levels built from intraday bars."""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from kterminal.domain.market import Bar
from kterminal.domain.sessions import TradingDayRule
from kterminal.domain.timeframes import H1, M5, Timeframe
from kterminal.strategy_engine import Period, PeriodLevels, period_warmup_bars
from kterminal.strategy_engine.testing import run_strategy
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.engine_strategies import Recorder
from tests.fixtures.instruments import XAUUSD

NEW_YORK = ZoneInfo("America/New_York")
SESSIONS = lab_catalog().sessions
NY_1700 = SESSIONS.trading_day_rule("ny_1700")
UTC_MIDNIGHT = SESSIONS.trading_day_rule("utc_midnight")
METALS = SESSIONS.calendar("metals_otc")


def ny(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=NEW_YORK).astimezone(UTC)


def hourly(
    start: datetime,
    end: datetime,
    *,
    is_open: Callable[[datetime], bool] = lambda _t: True,
    skip: Callable[[datetime], bool] = lambda _t: False,
    tf: Timeframe = H1,
) -> list[Bar]:
    """Bars over [start, end) with distinct, deterministic prices (high = 100 + n)."""
    out: list[Bar] = []
    t = start
    n = 0
    while t < end:
        if is_open(t) and not skip(t):
            n += 1
            base = Decimal(100 + n)
            out.append(Bar.of("XAUUSD", tf, t, base - 1, base, base - 2 - n % 3, base - 1))
        t += tf.duration
    return out


def key(rule: TradingDayRule, period: Period, ts: datetime) -> date:
    day = rule.trading_day(ts)
    if period is Period.DAY:
        return day
    if period is Period.WEEK:
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def check_against_brute_force(rule: TradingDayRule, bars: list[Bar]) -> PeriodLevels:
    """Feed ``bars`` and compare every bar's previous/current levels with a recomputation."""
    levels = PeriodLevels(rule)
    grouped: dict[Period, dict[date, list[Bar]]] = {period: {} for period in Period}
    for bar in bars:
        levels.update(bar)
        for period in Period:
            groups = grouped[period]
            groups.setdefault(key(rule, period, bar.open_time), []).append(bar)
            keys = list(groups)
            first_complete = bars[0].open_time == rule.day_bounds(keys[0])[0]
            current = levels.current(period)
            assert current is not None and current.start == keys[-1]
            assert current.high == max(b.high for b in groups[keys[-1]])
            assert current.low == min(b.low for b in groups[keys[-1]])
            assert current.open == groups[keys[-1]][0].open and current.close == bar.close
            previous = levels.previous(period)
            if len(keys) < 2 or (len(keys) == 2 and not first_complete):
                assert previous is None, (period, bar.open_time)
                continue
            assert previous is not None, (period, bar.open_time)
            assert previous.start == keys[-2]
            assert previous.high == max(b.high for b in groups[keys[-2]])
            assert previous.low == min(b.low for b in groups[keys[-2]])
            assert previous.bars == len(groups[keys[-2]]) and previous.complete
    return levels


def test_trading_days_roll_at_1700_new_york_and_skip_the_weekend() -> None:
    # Thu 2026-01-08 10:00 NY (mid-day) → Tue 2026-01-13, metals hours (closed Fri 17:00 →
    # Sun 18:00 New York)
    bars = hourly(ny(2026, 1, 8, 10), ny(2026, 1, 13, 12), is_open=METALS.is_open)
    levels = check_against_brute_force(NY_1700, bars)
    by_open = {b.open_time: b for b in bars}
    assert ny(2026, 1, 9, 17) not in by_open and ny(2026, 1, 11, 17) not in by_open
    # replay up to Sunday 18:00 New York: the first bar of Monday's trading day
    replay = PeriodLevels(NY_1700)
    for bar in bars:
        replay.update(bar)
        if bar.open_time == ny(2026, 1, 11, 18):
            break
    current, previous = replay.current("D"), replay.previous("D")
    assert current is not None and current.start == date(2026, 1, 12)
    assert previous is not None and previous.start == date(2026, 1, 9)  # Friday, not Sunday
    friday = [b for b in bars if NY_1700.trading_day(b.open_time) == date(2026, 1, 9)]
    assert previous.high == max(b.high for b in friday)
    # metals reopen at 18:00 after the daily 17:00-18:00 break
    assert previous.open_time == ny(2026, 1, 8, 18) and previous.close_time == ny(2026, 1, 9, 17)
    # the data starts on a Thursday: the week of Jan 5 is partial and never "previous"
    assert replay.previous("W") is None
    week = replay.current("W")
    assert week is not None and week.start == date(2026, 1, 12) and week.complete
    final = levels.current("D")  # Tuesday 2026-01-13 (until 12:00), previous = Monday
    assert final is not None and final.start == date(2026, 1, 13)
    monday = levels.previous("D")
    assert monday is not None and monday.open_time == ny(2026, 1, 11, 18)


def test_a_partial_first_period_is_never_reported_as_previous() -> None:
    bars = hourly(ny(2026, 1, 8, 10), ny(2026, 1, 13, 12), is_open=METALS.is_open)
    levels = PeriodLevels(NY_1700)
    levels.update(bars[0])
    first = levels.current("D")
    assert first is not None and not first.complete  # started at 10:00, the day at 17:00
    for bar in bars[1:]:
        levels.update(bar)
        if bar.open_time == ny(2026, 1, 8, 17):  # Friday's trading day begins
            assert levels.previous("D") is None  # Thursday was seen only from 10:00
        if bar.open_time == ny(2026, 1, 11, 18):  # Monday's begins
            previous = levels.previous("D")
            assert previous is not None and previous.start == date(2026, 1, 9)
    # the week of Jan 5 was seen from Thursday only: never a previous week
    assert levels.previous("W") is None
    # data that starts exactly at a trading day's start is complete from the first bar
    exact = PeriodLevels(NY_1700)
    exact.update(Bar.of("XAUUSD", H1, ny(2026, 1, 7, 17), 1, 2, 0.5, 1))
    day = exact.current("D")
    assert day is not None and day.complete and day.start == date(2026, 1, 8)


def test_a_holiday_without_bars_is_skipped() -> None:
    def holiday(t: datetime) -> bool:  # no data for trading day Wed 2026-01-14
        return NY_1700.trading_day(t) == date(2026, 1, 14)

    bars = hourly(ny(2026, 1, 11, 18), ny(2026, 1, 16, 12), is_open=METALS.is_open, skip=holiday)
    check_against_brute_force(NY_1700, bars)
    levels = PeriodLevels(NY_1700)
    for bar in bars:
        levels.update(bar)
        if NY_1700.trading_day(bar.open_time) == date(2026, 1, 15):
            previous = levels.previous("D")
            assert previous is not None and previous.start == date(2026, 1, 13)  # Tuesday
            break


def test_month_end_with_a_1700_rollover_and_daylight_saving_time() -> None:
    # 2026-09-30 (Wed) 17:00 EDT = 21:00 UTC starts trading day Oct 1, hence October; the
    # first bar of it opens after the daily break, at 18:00 EDT = 22:00 UTC
    bars = hourly(ny(2026, 8, 30, 18), ny(2026, 10, 2, 12), is_open=METALS.is_open)
    levels = PeriodLevels(NY_1700)
    for bar in bars:
        levels.update(bar)
        if bar.open_time == datetime(2026, 9, 30, 22, 0, tzinfo=UTC):
            break
    month, previous = levels.current("M"), levels.previous("M")
    assert month is not None and month.start == date(2026, 10, 1) and month.bars == 1
    assert previous is not None and previous.start == date(2026, 9, 1)
    september = [b for b in bars if NY_1700.trading_day(b.open_time).month == 9]
    assert previous.high == max(b.high for b in september)
    assert previous.close_time == datetime(2026, 9, 30, 21, 0, tzinfo=UTC)
    # the August period was seen from 2026-08-30 18:00 only: not complete, never previous
    check_against_brute_force(NY_1700, bars[:400])


def test_the_week_boundary_moves_with_new_york_daylight_saving_time() -> None:
    # Clocks go back on Sun 2026-11-01: Friday's day ends 21:00 UTC (EDT), Monday's
    # begins Sunday 17:00 EST = 22:00 UTC (the market reopens at 18:00 EST = 23:00 UTC).
    # The data starts a week earlier: a week first seen at the Sunday 18:00 reopen counts
    # as partial (the trading week starts at 17:00), so it never becomes "previous".
    bars = hourly(ny(2026, 10, 18, 18), ny(2026, 11, 4, 12), is_open=METALS.is_open)
    levels = check_against_brute_force(NY_1700, bars)
    replay = PeriodLevels(NY_1700)
    for bar in bars:
        replay.update(bar)
        if bar.open_time == datetime(2026, 11, 1, 23, 0, tzinfo=UTC):
            break
    day, week = replay.current("D"), replay.current("W")
    assert day is not None and day.start == date(2026, 11, 2)
    assert week is not None and week.start == date(2026, 11, 2) and week.bars == 1
    previous_week = replay.previous("W")
    assert previous_week is not None and previous_week.start == date(2026, 10, 26)
    assert previous_week.close_time == datetime(2026, 10, 30, 21, 0, tzinfo=UTC)
    assert levels.previous("M") is None  # October was seen from the 25th only


def test_crypto_days_weeks_and_months_follow_utc() -> None:
    start = datetime(2026, 1, 26, 0, 0, tzinfo=UTC)  # a Monday: complete from the start
    bars = hourly(start, start + timedelta(days=40))
    levels = check_against_brute_force(UTC_MIDNIGHT, bars)
    sunday = PeriodLevels(UTC_MIDNIGHT)
    for bar in bars:
        sunday.update(bar)
        if bar.open_time == datetime(2026, 2, 1, 23, 0, tzinfo=UTC):  # Sunday night
            break
    week = sunday.current("W")  # Monday 00:00 UTC → Sunday 24:00 UTC
    assert week is not None and week.start == date(2026, 1, 26) and week.bars == 7 * 24
    assert week.complete  # the data starts exactly at the week's start
    assert sunday.previous("M") is None  # January was seen from the 26th only
    month = sunday.current("M")
    assert month is not None and month.start == date(2026, 2, 1) and month.bars == 24
    current_month, previous_month = levels.current("M"), levels.previous("M")
    assert current_month is not None and current_month.start == date(2026, 3, 1)
    assert previous_month is not None and previous_month.start == date(2026, 2, 1)
    assert previous_month.bars == 28 * 24


def test_bars_must_arrive_in_order_and_periods_parse() -> None:
    levels = PeriodLevels(UTC_MIDNIGHT)
    bar = Bar.of("XAUUSD", M5, datetime(2026, 1, 5, tzinfo=UTC), 1, 2, 0.5, 1)
    levels.update(bar)
    with pytest.raises(ValueError, match="in order"):
        levels.update(bar)
    assert Period.parse("D") is Period.parse("day") is Period.parse("d") is Period.DAY
    assert Period.parse("month") is Period.MONTH and Period.parse("M") is Period.MONTH
    with pytest.raises(ValueError, match="unknown period"):
        Period.parse("m")  # minutes, not months


def test_warmup_bars_needed_for_previous_levels() -> None:
    # two whole periods plus two hours (a 25-hour day when the clocks go back), plus one
    assert period_warmup_bars("D", "5m") == 2 * 288 + 24 + 1
    assert period_warmup_bars(Period.WEEK, "1h") == 14 * 24 + 2 + 1
    assert period_warmup_bars("M", "15m") == 62 * 96 + 8 + 1
    with pytest.raises(ValueError, match="intraday"):
        period_warmup_bars("D", "1D")


def test_previous_day_is_known_after_a_warm_up_covering_a_full_day() -> None:
    warmup = hourly(ny(2026, 1, 6, 10), ny(2026, 1, 8, 9), is_open=METALS.is_open)
    live = hourly(ny(2026, 1, 8, 9), ny(2026, 1, 8, 12), is_open=METALS.is_open)
    result = run_strategy(
        Recorder,
        instrument=XAUUSD,
        bars=live,
        timeframe="1h",
        sessions=SESSIONS,
        warmup_bars=warmup,
    )
    assert result.fault is None
    recorder = result.runner._strategy  # type: ignore[union-attr]
    highs = recorder.previous_day_high  # type: ignore[union-attr]
    assert len(highs) == len(warmup) + len(live)
    assert highs[0] is None  # Tuesday from 10:00 only: no complete day yet
    wednesday = [b for b in warmup if NY_1700.trading_day(b.open_time) == date(2026, 1, 7)]
    assert highs[-1] == max(b.high for b in wednesday)  # Thursday's PDH = Wednesday's high
    assert recorder.indices == list(range(len(highs)))  # type: ignore[union-attr]

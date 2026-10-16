"""Golden scenarios for the script's own rules (lines 100-156 of 08_frvp_orb_ema.pine):
the opening range, the state trigger, the EMA filter, the once-per-day counters, the
levels window and the stale-range carry-over."""

from datetime import date

from kterminal.core.enums import SignalAction
from kterminal.indicators import Ema, feed
from kterminal.strategy_engine import PositionEventKind
from tests.unit.strategies.orb_breakout.helpers import (
    at,
    day_bars,
    hhmm,
    local,
    run,
    strategy_object,
)
from tests.unit.strategies.pine_port_support import entries, of_kind

TUE = date(2026, 1, 6)
WED = date(2026, 1, 7)
LONG, SHORT = SignalAction.LONG, SignalAction.SHORT
NO_FILTER = {"or_filter": False}

# ORH 101.5 (09:35 high), ORL 99 (09:40 low), midpoint 100.25. The 09:25 bar's wide
# wicks are outside the window and must not count.
OR_ROWS: dict[str, tuple[float, float, float, float] | float] = {
    "09:25": (100, 105, 95, 100),
    "09:30": (100, 101, 99.5, 100.5),
    "09:35": (100.5, 101.5, 100, 101),
    "09:40": (101, 101.2, 99, 100),
}


def test_range_is_the_wick_high_low_of_bars_opening_in_the_window() -> None:
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6)})
    result = run(bars, params=NO_FILTER)
    assert result.fault is None
    [signal] = entries(result)
    assert at([signal]) == [("09:45", LONG)]  # the first bar after the window can signal
    assert signal.metadata["or_high"] == 101.5  # not the 09:25 high, not the 09:45 high
    assert signal.metadata["or_low"] == 99.0
    assert signal.metadata["or_mid"] == 100.25
    assert signal.metadata["trigger"] == "ORB long"
    assert signal.metadata["stale_range"] is False
    assert signal.metadata["or_start"] == local(TUE, "09:30").isoformat()


def test_long_entry_stop_at_the_range_low_and_2r_from_the_signal_close() -> None:
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6)})
    [signal] = entries(run(bars, params=NO_FILTER))
    assert signal.signal is LONG
    assert float(signal.entry or 0) == 101.6  # the signal close (filled at the next open)
    assert float(signal.stop_loss or 0) == 99.0
    assert float(signal.take_profit or 0) == 106.8  # 101.6 + 2 × 2.6
    assert signal.reason == "ORB long"


def test_short_mirrors_the_long() -> None:
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 100.1, 98.5, 98.9)})
    [signal] = entries(run(bars, params=NO_FILTER))
    assert at([signal]) == [("09:45", SHORT)]
    assert float(signal.stop_loss or 0) == 101.5
    assert float(signal.take_profit or 0) == 93.7  # 98.9 − 2 × 2.6
    assert signal.metadata["trigger"] == "ORB short"


def test_trigger_is_strict_a_close_at_the_level_does_not_signal() -> None:
    bars = day_bars(
        TUE, {**OR_ROWS, "09:45": (100, 101.5, 99.9, 101.5), "09:50": (101.5, 101.6, 101, 101.51)}
    )
    assert at(entries(run(bars, params=NO_FILTER))) == [("09:50", LONG)]


def test_at_most_one_long_per_day_even_after_the_trade_is_gone() -> None:
    # Long at 09:45, stopped out at 10:30 (low 98.9 ≤ ORL); the close is back above ORH
    # at 11:00 but the day's long is used up. The 10:30 close below ORL is the day's short.
    bars = day_bars(
        TUE,
        {
            **OR_ROWS,
            "09:45": (100, 101.8, 99.9, 101.6),
            "10:30": (101.6, 101.6, 98.0, 98.5),
            "11:00": (98.5, 102.5, 98.5, 102),
        },
    )
    result = run(bars, params=NO_FILTER)
    assert at(entries(result)) == [("09:45", LONG), ("10:30", SHORT)]
    closed = of_kind(result, PositionEventKind.CLOSED)
    assert closed[0].reason is not None and closed[0].reason.value == "STOP_LOSS"
    assert hhmm(closed[0].time) == "10:35"  # the 10:30 bar's close


def test_signals_only_while_the_levels_window_is_open() -> None:
    # Inside the range all day; beyond it only from 16:00 (outside 09:30-16:00) and
    # before the next day's range.
    bars = day_bars(TUE, {**OR_ROWS, "16:00": (100, 103, 100, 102.5), "16:30": 97.0})
    bars += day_bars(WED, {"08:00": 103.0, "08:30": 96.0}, price=103, end="09:30")
    assert entries(run(bars, params=NO_FILTER)) == []


def test_no_signal_during_the_opening_range_of_the_next_day() -> None:
    # Tuesday's unused long cannot fire on Wednesday's OR bars: orStart replaced the range.
    bars = day_bars(TUE, OR_ROWS)
    bars += day_bars(
        WED,
        {"09:30": (100, 102, 100, 101.9), "09:35": (101.9, 102.2, 101.8, 102), "09:40": 102.1},
        end="09:45",
    )
    assert entries(run(bars, params=NO_FILTER)) == []


def test_ema_filter_blocks_without_consuming_and_the_state_fires_later() -> None:
    # Price falls from 110 into the range, so EMA9 < EMA20 at 09:45: the close above ORH
    # is blocked and does not use up the long. Price then rises; the long fires on the
    # first bar where EMA9 > EMA20 while the close is still above ORH — hours later.
    rows = {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6), "13:00": 104.0, "13:05": 106.0}
    bars = day_bars(TUE, rows, price=110)
    closes = [float(b.close) for b in bars]
    fast, slow = feed(Ema(9).update, closes), feed(Ema(20).update, closes)
    first_bull = next(
        i
        for i, bar in enumerate(bars)
        if hhmm(bar.open_time) >= "09:45" and closes[i] > 101.5 and fast[i] > slow[i]
    )
    assert hhmm(bars[first_bull].open_time) in ("13:00", "13:05")
    result = run(bars)
    [signal] = entries(result)
    assert signal.bar_time == bars[first_bull].open_time
    assert signal.metadata["ema_fast"] == fast[first_bull]
    assert signal.metadata["ema_slow"] == slow[first_bull]
    # without the filter the same bars signal at 09:45
    assert at(entries(run(bars, params=NO_FILTER))) == [("09:45", LONG)]


def test_ema_filter_short_needs_ema9_below_ema20() -> None:
    falling = {**OR_ROWS, "09:45": (100, 100.1, 98.5, 98.9)}
    assert at(entries(run(day_bars(TUE, falling, price=110)))) == [("09:45", SHORT)]
    # coming from below the EMAs are bullish at 09:45: the short is blocked all day
    assert entries(run(day_bars(TUE, falling, price=90))) == []


def test_na_emas_block_until_they_exist() -> None:
    # A history starting at 09:30: at 09:45 (the 4th bar) EMA20 is na, so `bull` is false
    # (any comparison with na is). The long fires once both EMAs exist and EMA9 > EMA20.
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6)}, start="09:30")
    closes = [float(b.close) for b in bars]
    fast, slow = feed(Ema(9).update, closes), feed(Ema(20).update, closes)
    expected = next(i for i in range(len(bars)) if fast[i] > slow[i])
    assert expected == 19  # the first bar with an EMA20
    [signal] = entries(run(bars))
    assert signal.bar_time == bars[expected].open_time


def test_long_and_short_on_the_same_day() -> None:
    bars = day_bars(
        TUE,
        {**OR_ROWS, "10:00": (100, 102, 100, 101.9), "13:20": (101.9, 101.9, 98.0, 98.2)},
    )
    result = run(bars, params=NO_FILTER)
    assert at(entries(result)) == [("10:00", LONG), ("13:20", SHORT)]


def test_stale_range_carries_over_to_a_day_without_or_bars() -> None:
    # Tuesday: long at 09:45. Wednesday has no bar opening in 09:30-09:45 (a gap), so
    # Tuesday's range stays current: its long is used, its short is still available.
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6)})
    bars += day_bars(
        WED,
        {"10:00": (100, 103, 100, 102.9), "11:00": (102.9, 102.9, 98, 98.5)},
        skip=("09:30", "09:35", "09:40"),
    )
    result = run(bars, params=NO_FILTER)
    signals = entries(result)
    assert [(s.bar_time.date() if s.bar_time else None, s.signal) for s in signals] == [
        (TUE, LONG),
        (WED, SHORT),
    ]
    stale = signals[1]
    assert stale.metadata["stale_range"] is True
    assert stale.metadata["or_start"] == local(TUE, "09:30").isoformat()
    assert float(stale.stop_loss or 0) == 101.5


def test_a_new_range_resets_the_counters() -> None:
    day = {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6)}
    bars = day_bars(TUE, day) + day_bars(WED, day)
    result = run(bars, params=NO_FILTER)
    assert [(s.bar_time.date() if s.bar_time else None, s.signal) for s in entries(result)] == [
        (TUE, LONG),
        (WED, LONG),
    ]


def test_first_bar_inside_the_window_starts_the_range() -> None:
    # Pine's inOR[1] is false on the first bar: a history starting at 09:35 starts the
    # range there.
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6)}, start="09:35")
    [signal] = entries(run(bars, params=NO_FILTER))
    assert signal.metadata["or_start"] == local(TUE, "09:35").isoformat()
    assert signal.metadata["or_high"] == 101.5


def test_a_gap_inside_the_window_keeps_one_range() -> None:
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 100.5, 98.0, 98.5)}, skip=("09:35",))
    [signal] = entries(run(bars, params=NO_FILTER))
    assert signal.metadata["or_high"] == 101.2  # 09:30 and 09:40 only
    assert signal.metadata["or_low"] == 99.0
    assert signal.signal is SHORT


def test_counters_are_consumed_during_warm_up_like_the_markers() -> None:
    # The long fired on a warm-up bar (discarded: nothing trades during warm-up) but
    # the script drew its marker, so the day's long is used up for the live bars.
    bars = day_bars(TUE, {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6), "13:00": 98.0})
    cut = next(i for i, b in enumerate(bars) if hhmm(b.open_time) == "12:00")
    result = run(bars[cut:], params=NO_FILTER, warmup_bars=bars[:cut])
    assert at(entries(result)) == [("13:00", SHORT)]
    current = strategy_object(result)._range
    assert current is not None and current.long_done and current.short_done


def test_fifteen_minute_chart_uses_the_single_0930_bar() -> None:
    bars = day_bars(
        TUE,
        {"09:30": (100, 101.5, 99, 100.5), "09:45": (100.5, 102, 100.4, 101.9)},
        timeframe="15m",
    )
    [signal] = entries(run(bars, params=NO_FILTER, timeframe="15m"))
    assert at([signal]) == [("09:45", LONG)]
    assert signal.metadata["or_high"] == 101.5


def test_two_runs_give_identical_signals() -> None:
    rows = {**OR_ROWS, "09:45": (100, 101.8, 99.9, 101.6), "13:00": 104.0, "13:20": 97.0}
    bars = day_bars(TUE, rows, price=110) + day_bars(WED, rows, price=97)
    first = [s.model_dump(mode="json") for s in run(bars).signals]
    second = [s.model_dump(mode="json") for s in run(bars).signals]
    assert first == second
    assert first  # the scenario does signal


def test_a_gap_from_one_range_window_into_the_next_is_not_a_new_start() -> None:
    # Tuesday's data stops at the 09:40 bar and resumes on Wednesday at 09:30: the two
    # bars are consecutive and both inside the window, so `inOR[1]` is true and no new
    # range starts (session_started in docs/05 §5.2.3). Wednesday's OR bars widen
    # Tuesday's range, which forms on Wednesday 09:45.
    bars = day_bars(TUE, OR_ROWS, end="09:45")
    bars += day_bars(
        WED,
        {
            "09:30": (100, 102.5, 100, 102),
            "09:35": (102, 102.2, 101.6, 102),
            "09:40": 102.0,
            "09:45": (102, 103, 102, 102.6),
        },
        start="09:30",
    )
    [signal] = entries(run(bars, params=NO_FILTER))
    assert signal.bar_time == local(WED, "09:45")
    assert signal.metadata["or_start"] == local(TUE, "09:30").isoformat()
    assert signal.metadata["or_high"] == 102.5  # Wednesday's 09:30 high widened it
    assert signal.metadata["or_low"] == 99.0  # Tuesday's 09:40 low
    assert signal.metadata["stale_range"] is True

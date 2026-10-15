"""Golden scenarios for script 5's sniper rules (L128-L667 of 05_smart_money_suite_v4.pine):
the BOS through the latest swing, the four score points and Min Score, the order
block, the cross evaluated before the level update, levels never consumed, the stop
basis and the 2R bracket, and the short mirror. Hand-built bars (scenarios.py) with
the script's shortest lengths: 5/5 swings, 3/3 order blocks."""

import math
from typing import Any

import pytest

from kterminal.core.enums import SignalAction
from kterminal.indicators import Atr, feed
from kterminal.strategies.smc_sniper import SmcSniper
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import XAUUSD
from tests.unit.strategies.pine_port_support import (
    actions,
    dumps,
    entries,
    index_of,
    make_bars,
    run,
    strategy_object,
)
from tests.unit.strategies.smc_sniper.scenarios import (
    BASE,
    LSH,
    SHORT_LENGTHS,
    SIGNAL_BAR,
    Row,
    mirror,
    ramp,
)

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT


def sniper(rows: list[Row], **params: Any) -> StrategyTestResult:
    result = run(SmcSniper, make_bars(rows), params={**SHORT_LENGTHS, **params})
    assert result.fault is None and result.rejected == []
    return result


def atr_at(rows: list[Row], index: int) -> float:
    highs, lows, closes = ([r[i] for r in rows] for i in (1, 2, 3))
    return feed(Atr(14).update, highs, lows, closes)[index]


def test_bos_long_with_structure_zone_and_momentum() -> None:
    result = sniper(BASE)
    [signal] = result.signals
    assert index_of(signal) == SIGNAL_BAR and signal.signal is LONG
    meta = signal.metadata
    assert meta["pine_signal"] == "sniper_long"
    assert meta["trigger"] == "Sniper Long"
    assert meta["structure_label"] == "BOS"  # upt starts true: not a CHoCH (L397, L413)
    assert meta["broken_level"] == LSH
    assert meta["lsh_bar_index"] == 16
    assert meta["points"] == {"trend": False, "structure": True, "zone": True, "momentum": True}
    assert meta["score"] == 3 and signal.reason == "Sniper Long 3/4"
    assert meta["ema200"] is None  # na before 200 bars: no trend point
    assert meta["zones"] == [{"kind": "OB", "top": 109.0, "bottom": 105.0, "bar_index": 10}]
    rsi, roc = meta["rsi"], meta["roc"]
    assert isinstance(rsi, float) and rsi > 55
    assert roc == pytest.approx(108.8 - 107.4)  # close − close[5]


def test_stop_falls_back_to_the_bar_low_without_a_swing_low_and_target_is_2r() -> None:
    # No 5/5 pivot low is confirmed by bar 23 (bar 20's needs five bars on its right),
    # so the stop is the signal bar's low − 0.5 × ATR(14) (L645) and the target 2R from
    # the close (L646).
    [signal] = sniper(BASE).signals
    atr = atr_at(BASE, SIGNAL_BAR)
    stop = 107.8 - 0.5 * atr
    target = 108.8 + 2.0 * (108.8 - stop)
    meta = signal.metadata
    assert meta["stop_basis"] == "bar_low" and meta["lsl"] is None
    assert meta["script_stop"] == stop and meta["script_target"] == target
    assert meta["atr"] == atr
    assert signal.stop_loss == XAUUSD.round_price(signal.stop_loss or 0)
    assert float(signal.stop_loss or 0) == pytest.approx(stop, abs=0.005)
    assert float(signal.take_profit or 0) == pytest.approx(target, abs=0.005)
    assert float(signal.entry or 0) == 108.8


def test_min_score_4_blocks_a_three_point_signal() -> None:
    assert sniper(BASE, sniper_min=4).signals == []


def test_zone_point_needs_the_order_block() -> None:
    # ob_on off ('Enable Order Blocks'): the block is never listed, the score drops to 2.
    assert sniper(BASE, ob_on=False).signals == []
    assert [s.metadata["score"] for s in sniper(BASE, ob_on=False, sniper_min=2).signals] == [2]


def test_order_blocks_are_capped_first_in_first_out() -> None:
    # Bar 20 is a bearish 3/3 pivot-low candle too: its block (107.0-107.2) is pushed on
    # bar 23. With ob_max 1 it shifts bar 10's block out and the close 108.8 is in no
    # block any more.
    strategy = strategy_object(sniper(BASE))
    assert [(z.bottom, z.top, z.bar_index) for z in strategy.bull_obs.zones] == [
        (105.0, 109.0, 10),
        (107.0, 107.2, 20),
    ]
    capped = sniper(BASE, ob_max=1)
    assert capped.signals == []
    assert [z.bar_index for z in strategy_object(capped).bull_obs.zones] == [20]


def test_momentum_needs_rsi_above_55() -> None:
    # The same pattern after a fall from 127 to 109 instead of a rise: RSI(14) is still
    # weak (≈ 22) on the BOS bar although close > close[5]. No momentum point: 2 of 4.
    falling: list[Row] = [(127, 127.5, 126.5, 127)]
    close = 127.0
    for step in (2, 2, 2, 2, 2, 2, 2, 2, 2):
        falling.append((close, close + 0.3, close - step - 0.2, close - step))
        close -= step
    rows = falling + BASE[10:]
    assert sniper(rows).signals == []
    [signal] = sniper(rows, sniper_min=2).signals
    meta = signal.metadata
    assert index_of(signal) == SIGNAL_BAR
    assert meta["points"] == {"trend": False, "structure": True, "zone": True, "momentum": False}
    rsi, roc = meta["rsi"], meta["roc"]
    assert isinstance(rsi, float) and isinstance(roc, float)
    assert rsi < 55 and roc > 0
    # with a 5/5 swing low now known (bar 10, 104.8) the stop rests on it
    assert meta["stop_basis"] == "swing_low" and meta["lsl"] == 104.8


def test_trend_point_needs_close_above_ema50_above_ema200() -> None:
    # 230 bars rising from 77 to 100 before the same pattern: EMA200 exists and
    # close > EMA50 > EMA200, so the BOS scores 4/4 and passes Min Score 4.
    rows = ramp(230, 77.0, 100.0) + BASE
    [signal] = sniper(rows, sniper_min=4).signals
    meta = signal.metadata
    assert index_of(signal) == 230 + SIGNAL_BAR
    assert meta["points"] == {"trend": True, "structure": True, "zone": True, "momentum": True}
    ema50, ema200 = meta["ema50"], meta["ema200"]
    assert isinstance(ema50, float) and isinstance(ema200, float)
    assert 108.8 > ema50 > ema200
    assert signal.reason == "Sniper Long 4/4"
    # falling into the pattern instead, the EMAs are bearish: back to 3/4, blocked at 4
    assert sniper(ramp(230, 123.0, 100.0) + BASE, sniper_min=4).signals == []


def test_short_mirrors_the_long_and_the_first_bearish_bos_is_a_choch() -> None:
    long_signal = sniper(BASE).signals[0]
    [signal] = sniper(mirror(BASE)).signals
    assert index_of(signal) == SIGNAL_BAR and signal.signal is SHORT
    meta = signal.metadata
    assert meta["pine_signal"] == "sniper_short" and meta["trigger"] == "Sniper Short"
    assert meta["structure_label"] == "CHoCH"  # upt was true (L398, L424)
    assert meta["points"] == long_signal.metadata["points"]
    assert meta["stop_basis"] == "bar_high"
    assert meta["broken_level"] == pytest.approx(200 - LSH)
    assert meta["zones"] == [{"kind": "OB", "top": 95.0, "bottom": 91.0, "bar_index": 10}]
    long_stop, long_target = (
        long_signal.metadata["script_stop"],
        long_signal.metadata["script_target"],
    )
    assert isinstance(long_stop, float) and isinstance(long_target, float)
    assert meta["script_stop"] == pytest.approx(200 - long_stop)
    assert meta["script_target"] == pytest.approx(200 - long_target)
    assert strategy_object(sniper(mirror(BASE))).upt is False


def test_levels_are_never_consumed() -> None:
    # After the BOS of 108.6 the close dips back to 108.4 and crosses 108.6 again on bar
    # 25: a second BOS of the same level and a second signal (L385-396). Its stop now
    # rests on the swing low of bar 20, confirmed on bar 25 itself (lsl is updated
    # before the bracket is drawn, L391-393, L645).
    rows = [*BASE, (108.8, 108.9, 108.3, 108.4), (108.4, 109.0, 108.3, 108.9)]
    result = sniper(rows)
    assert actions(result) == [(23, LONG), (25, LONG)]
    second = result.signals[1].metadata
    assert second["broken_level"] == LSH
    assert second["stop_basis"] == "swing_low" and second["lsl"] == 106.8
    assert second["script_stop"] == 106.8 - 0.5 * atr_at(rows, 25)


def test_the_cross_is_evaluated_before_the_level_update() -> None:
    # After the BOS a new, higher swing high (110.0, bar 25) is confirmed on bar 30 while
    # the close (109.0) is already above the old level 108.6. On bar 31 the close 110.5
    # is above the new level, but the cross compares bar 30's close with the level as
    # passed on bar 30 — the old 108.6 — so there is no BOS (L384-386). A port using the
    # level's end-of-bar history would see 109.0 <= 110.0 and signal a phantom BOS.
    rows = [
        *BASE,
        (108.8, 109.4, 108.7, 109.3),  # 24
        (109.3, 110.0, 109.2, 109.8),  # 25: 5/5 pivot high 110.0
        (109.8, 109.9, 109.4, 109.5),  # 26
        (109.5, 109.7, 109.2, 109.3),  # 27
        (109.3, 109.5, 109.0, 109.2),  # 28
        (109.2, 109.4, 108.9, 109.1),  # 29
        (109.1, 109.3, 108.9, 109.0),  # 30: lsh = 110.0 (from 108.6)
        (109.0, 110.7, 108.9, 110.5),  # 31: close above 110.0
        (110.5, 110.6, 109.6, 109.7),  # 32: back below 110.0
        (109.7, 110.4, 109.6, 110.3),  # 33: a real cross of 110.0
    ]
    result = sniper(rows, sniper_min=1)
    assert actions(result) == [(23, LONG), (33, LONG)]
    assert result.signals[1].metadata["broken_level"] == 110.0
    assert result.signals[1].metadata["lsh_bar_index"] == 25
    closes = [r[3] for r in rows]
    assert closes[31] > 110.0 and closes[30] <= 110.0  # what the end-of-bar reading sees


def test_no_signal_before_a_swing_is_known() -> None:
    # The first rows only rise: no 5/5 pivot high is confirmed, so lsh is na and the
    # close cannot break anything (L395: not na(lsh)).
    result = sniper(BASE[:10], sniper_min=1)
    assert result.signals == []
    assert math.isnan(strategy_object(result).lsh)


def test_two_runs_give_identical_signals() -> None:
    rows = [*BASE, (108.8, 108.9, 108.3, 108.4), (108.4, 109.0, 108.3, 108.9)]
    first, second = dumps(sniper(rows)), dumps(sniper(rows))
    assert first == second and len(first) == 2
    assert entries(sniper(rows))  # the scenario does trade

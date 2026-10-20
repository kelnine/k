"""The doc 13 decisions applied to S6: D7 (limit at the CISD level, 12-bar expiry, cancel
when TP1 trades first, TP1-only / TP2-only, the market comparison), D4 (a new CISD
replaces the order or trade: the engine's replace, or its reverse in market mode), D3
(levels on the wrong side, the gap guard), the script's 4,500-bar tracking limit, the
params and determinism.

The tapes are dojis around 100 (they start no run) with ``req_sweep`` off, so a CISD
fires exactly where the scripted rows make one: ``BEAR`` is an up-close run from 100.0
with a high of 100.8 and a close at 99.6 — a short limit at 100.0, stop 100.8, R 0.8,
TP1 99.2, TP2 98.4.
"""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from kterminal.core.enums import OrderType, SignalAction
from kterminal.strategies.cisd_sweep import CisdSweep, CisdSweepParams
from kterminal.strategy_engine import CloseReason, PositionEventKind
from kterminal.strategy_engine.registry import definition_from_class
from kterminal.strategy_engine.testing import StrategyTestResult
from tests.fixtures.instruments import T0
from tests.unit.strategies.cisd_sweep.scenario import Row, Tape, run_tape
from tests.unit.strategies.pine_port_support import dumps, of_kind

LONG, SHORT = SignalAction.LONG, SignalAction.SHORT
EXIT_LONG, EXIT_SHORT = SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT
NO_TRADE = SignalAction.NO_TRADE

BEFORE = 30  # dojis before the setup: the ATR settles at 0.3
S = BEFORE + 2  # the CISD bar
BEAR: tuple[Row, ...] = (
    (100.0, 100.6, 99.95, 100.5),  # S-2 up-close run: open 100.0
    (100.5, 100.8, 100.4, 100.7),  # S-1 run high 100.8
    (100.7, 100.75, 99.5, 99.6),  # S   bearish CISD: close 99.6 < 100.0
)
FILL: Row = (99.6, 100.05, 99.5, 99.55)  # high >= 100.0: the short limit fills
# after the fill: a new up-close run from 99.55 and a close below it (same direction)
SAME_AGAIN: tuple[Row, ...] = (
    (99.55, 99.9, 99.5, 99.85),  # run open 99.55
    (99.85, 99.9, 99.2, 99.3),  # bearish CISD: 99.55, stop 99.9
)
# after the fill: a close above the open of the down run started by the CISD bar (100.7)
OPPOSITE: Row = (99.55, 100.79, 99.5, 100.75)  # bullish CISD: 100.7, stop 99.5 (no stop hit)


def tape(*after: Row, tail: int = 20, level: float | None = None, setup: Any = BEAR) -> Tape:
    t = Tape(T0, doji=True).quiet(BEFORE).then(*setup, *after)
    last_close = (setup[-1] if not after else after[-1])[3]
    return t.quiet(tail, level=level if level is not None else last_close)


def cisd(t: Tape, **params: Any) -> StrategyTestResult:
    kwargs = params.pop("kwargs", {})
    return run_tape(CisdSweep, t, params={"req_sweep": False, **params}, **kwargs)


def _index(t: Any) -> int:
    """Bar index of an instant on the 5m tape (a bar's open time)."""
    return int((t - T0).total_seconds() // 300)


def acts(result: StrategyTestResult) -> list[tuple[int, SignalAction]]:
    return [(_index(s.bar_time), s.signal) for s in result.signals]


def opened(result: StrategyTestResult) -> list[tuple[int, Decimal | None]]:
    return [(_index(e.time), e.price) for e in of_kind(result, PositionEventKind.OPENED)]


def closed(result: StrategyTestResult) -> list[tuple[CloseReason | None, Decimal | None]]:
    return [(e.reason, e.price) for e in of_kind(result, PositionEventKind.CLOSED)]


def test_definition_rules() -> None:
    meta = definition_from_class(CisdSweep).meta
    assert meta.on_opposite_signal == "reverse"  # D4 market mode: reverse on the flip
    assert meta.skip_entry_beyond_levels is True  # D3 (market entries only)
    assert meta.warmup_bars == 600 and meta.timeframes == ()


# ── D7: the limit at the CISD level ────────────────────────────────────────────────
def test_the_limit_fills_at_the_level_and_runs_to_the_chosen_target() -> None:
    t = tape(FILL, (99.55, 99.6, 98.9, 99.0), (99.0, 99.05, 98.3, 98.4), level=98.4)
    tp2 = cisd(t)
    (signal,) = tp2.signals
    assert (signal.signal, signal.order_type, signal.expires_after_bars) == (
        SHORT,
        OrderType.LIMIT,
        12,
    )
    assert opened(tp2) == [(S + 1, Decimal("100.00"))]
    assert closed(tp2) == [(CloseReason.TAKE_PROFIT, Decimal("98.40"))]
    tp1 = cisd(t, target="tp1")  # the TP1-only instance: same order, target 1R
    assert tp1.signals[0].take_profit == Decimal("99.20")
    assert closed(tp1) == [(CloseReason.TAKE_PROFIT, Decimal("99.20"))]


def test_an_unfilled_limit_expires_after_12_bars() -> None:
    t = tape(tail=12, level=99.6).then((99.6, 100.2, 99.55, 100.1)).quiet(5, level=100.1)
    result = cisd(t)
    (expired,) = of_kind(result, PositionEventKind.ORDER_EXPIRED)
    assert expired.time == T0 + (S + 13) * (t.timeframe.duration)  # the close of S+12
    assert opened(result) == []  # S+13 reaches 100.0 too late
    assert acts(result) == [(S, SHORT)]  # the book expired it: no cancel signal
    longer = cisd(t, limit_expiry_bars=13)
    assert opened(longer) == [(S + 13, Decimal("100.00"))]


def test_the_limit_is_cancelled_when_tp1_trades_before_the_fill() -> None:
    t = tape((99.2, 99.35, 99.05, 99.2), (99.2, 100.2, 99.15, 99.25), level=99.25)
    result = cisd(t)
    assert acts(result) == [(S, SHORT), (S + 1, EXIT_SHORT)]
    cancel = result.signals[1]
    assert cancel.reason == "cancel the CISD limit: TP1 traded before the fill"
    assert cancel.metadata == {
        "trigger": "order cancelled",
        "detail": "TP1 traded before the fill",
        "order_entry": "100.00",
        "order_tp1": "99.20",
        "order_bar_index": S,
        "bar_index": S + 1,
    }
    assert opened(result) == []  # S+2 reaches 100.0: the order is gone
    kept = cisd(t, cancel_on_tp1=False)
    assert acts(kept) == [(S, SHORT)]
    assert opened(kept) == [(S + 2, Decimal("100.00"))]


def test_tp1_beyond_the_signal_close_cancels_from_the_next_bar_only() -> None:
    setup = (*BEAR[:2], (100.7, 100.75, 98.9, 99.0))  # close 99.0 is already past TP1 99.2
    t = tape(setup=setup, level=99.0)
    result = cisd(t)
    assert acts(result) == [(S, SHORT), (S + 1, EXIT_SHORT)]


def test_a_fill_on_the_bar_that_also_trades_tp1_is_kept() -> None:
    # S+1 reaches 100.0 and TP1 99.2: the book fills (its path is unknown), no cancel
    t = tape((99.6, 100.05, 99.1, 99.3), level=99.4)
    result = cisd(t, target="tp1")
    assert acts(result) == [(S, SHORT)]
    assert opened(result) == [(S + 1, Decimal("100.00"))]
    # TP1 counts on the fill bar only if the bar closes beyond it (it closed at 99.3)
    assert closed(result) == []


# ── D4: a new CISD replaces the order or the trade ─────────────────────────────────
def test_a_new_cisd_replaces_the_resting_order() -> None:
    t = tape((99.6, 99.9, 99.5, 99.85), (99.85, 99.88, 99.3, 99.35), level=99.5)
    result = cisd(t)
    assert acts(result) == [(S, SHORT), (S + 2, EXIT_SHORT), (S + 2, SHORT)]
    cancel, entry = result.signals[1:]
    assert cancel.metadata["detail"] == "replaced by a new CISD"
    assert (entry.entry, entry.stop_loss, entry.take_profit) == (
        Decimal("99.60"),
        Decimal("99.90"),
        Decimal("99.00"),
    )


def test_a_same_direction_cisd_exits_the_trade_and_enters_again() -> None:
    t = tape(FILL, *SAME_AGAIN, level=99.4)
    result = cisd(t)
    assert acts(result) == [(S, SHORT), (S + 3, EXIT_SHORT), (S + 3, SHORT)]
    exit_ = result.signals[1]
    assert (exit_.reason, exit_.metadata["trigger"]) == ("replaced by a new CISD", "trade replaced")
    assert closed(result) == [(CloseReason.SIGNAL_EXIT, Decimal("99.40"))]  # next open
    assert opened(result) == [(S + 1, Decimal("100.00")), (S + 4, Decimal("99.55"))]
    assert result.signals[2].entry == Decimal("99.55")


def test_an_opposite_cisd_exits_the_trade_and_rests_the_new_limit() -> None:
    t = tape(FILL, OPPOSITE, level=100.75)
    result = cisd(t)
    assert acts(result) == [(S, SHORT), (S + 2, EXIT_SHORT), (S + 2, LONG)]
    long = result.signals[2]
    assert (long.entry, long.stop_loss, long.take_profit, long.order_type) == (
        Decimal("100.70"),
        Decimal("99.50"),
        Decimal("103.10"),
        OrderType.LIMIT,
    )
    assert long.metadata["trigger"] == "Bullish CISD"
    # the short closes at the next open, not when the long limit fills
    assert closed(result) == [(CloseReason.SIGNAL_EXIT, Decimal("100.75"))]


# ── the market comparison instance (D7) with D3 ────────────────────────────────────
def test_market_mode_fills_at_the_next_open_with_the_script_levels() -> None:
    t = tape((99.6, 99.7, 98.3, 98.4), level=98.4)
    result = cisd(t, entry="market")
    (signal,) = result.signals
    assert (signal.order_type, signal.entry, signal.stop_loss, signal.take_profit) == (
        OrderType.MARKET,
        Decimal("99.60"),  # the reference: the signal close
        Decimal("100.80"),
        Decimal("98.40"),  # TP2 from the CISD level, as the script prints it
    )
    assert signal.expires_after_bars is None
    assert signal.metadata["script_entry"] == 100.0
    assert opened(result) == [(S + 1, Decimal("99.60"))]
    assert closed(result) == [(CloseReason.TAKE_PROFIT, Decimal("98.40"))]


def test_market_mode_skips_a_target_already_passed_at_the_close() -> None:
    setup = (*BEAR[:2], (100.7, 100.75, 98.9, 99.0))  # TP1 99.2 above the close
    result = cisd(tape(setup=setup, level=99.0), entry="market", target="tp1")
    (signal,) = result.signals
    assert (signal.signal, signal.reason, signal.persist) == (NO_TRADE, "TARGET_WRONG_SIDE", True)
    assert signal.metadata["pine_signal"] == "bearCisd"
    assert result.events == []


def test_market_mode_skips_an_entry_whose_open_has_passed_the_target() -> None:
    t = tape((98.3, 98.35, 98.2, 98.3), level=98.3)  # gaps below TP2 98.4
    result = cisd(t, entry="market")
    (cancelled,) = of_kind(result, PositionEventKind.ORDER_CANCELLED)
    assert cancelled.detail == "OPEN_BEYOND_TARGET"
    assert opened(result) == []


def test_market_mode_reverses_on_an_opposite_cisd() -> None:
    t = tape((99.6, 99.7, 99.5, 99.55), OPPOSITE, level=100.75)
    result = cisd(t, entry="market")
    assert acts(result) == [(S, SHORT), (S + 2, LONG)]  # the engine's reverse: no EXIT
    assert closed(result) == [(CloseReason.REVERSAL, Decimal("100.75"))]
    assert opened(result) == [(S + 1, Decimal("99.60")), (S + 3, Decimal("100.75"))]


def test_market_mode_replaces_a_same_direction_trade() -> None:
    t = tape((99.6, 99.7, 99.5, 99.55), *SAME_AGAIN, level=99.3)
    result = cisd(t, entry="market")
    assert acts(result) == [(S, SHORT), (S + 3, EXIT_SHORT), (S + 3, SHORT)]
    assert closed(result) == [(CloseReason.SIGNAL_EXIT, Decimal("99.30"))]


def test_an_untradable_new_cisd_still_ends_the_trade() -> None:
    # a short CISD with R 0.1 whose TP2 (99.35) is above its close (99.1): no trade, but
    # the script's tracker drops the old trade all the same
    t = tape((99.6, 99.7, 99.5, 99.55), (99.55, 99.65, 99.5, 99.6), (99.6, 99.62, 99.0, 99.1))
    result = cisd(t, entry="market")
    assert acts(result) == [(S, SHORT), (S + 3, EXIT_SHORT), (S + 3, NO_TRADE)]
    assert result.signals[2].reason == "TARGET_WRONG_SIDE"
    assert closed(result)[0][0] is CloseReason.SIGNAL_EXIT


# ── D3 on limits, no target, the tracking limit ────────────────────────────────────
def test_a_limit_whose_target_rounds_onto_the_entry_is_not_traded() -> None:
    result = cisd(tape(), target="tp1", tp1_r=0.005)  # TP1 99.996 → 100.00 on the tick
    (signal,) = result.signals
    assert (signal.signal, signal.reason) == (NO_TRADE, "TARGET_WRONG_SIDE")


def test_a_zero_r_target_leaves_the_trade_without_a_take_profit() -> None:
    result = cisd(tape(FILL, level=99.55), tp2_r=0.0)  # tp2R 0: TP 2 is na (L736)
    (signal,) = result.signals
    assert signal.take_profit is None and signal.metadata["script_tp2"] is None
    assert opened(result) == [(S + 1, Decimal("100.00"))]


def test_the_trade_ends_when_the_script_stops_tracking_it() -> None:
    t = tape(FILL, tail=4_505, level=99.55)
    result = cisd(t)
    assert acts(result) == [(S, SHORT), (S + 4_501, EXIT_SHORT)]  # bar_index − trBar > 4500
    exit_ = result.signals[1]
    assert exit_.reason == "SESSION_CLOSE" and exit_.metadata["trigger"] == "tracking ended"
    assert closed(result) == [(CloseReason.SESSION_CLOSE, Decimal("99.55"))]


# ── params and determinism ─────────────────────────────────────────────────────────
def test_params_follow_the_pine_inputs_and_validate() -> None:
    p = CisdSweepParams()
    assert (p.req_sweep, p.sweep_look, p.min_body, p.pv_l, p.pv_r) == (True, 12, 0.3, 5, 5)
    assert (p.tp1_r, p.tp2_r, p.sig_window, p.tz) == (1.0, 2.0, "Any time", "America/New_York")
    assert (p.asia_sess, p.lon_sess, p.ny_am_sess, p.ny_pm_sess) == (
        "2000-0000:1234567",
        "0200-0500:1234567",
        "0930-1200:1234567",
        "1330-1600:1234567",
    )
    assert (p.entry, p.target, p.limit_expiry_bars, p.cancel_on_tp1) == ("limit", "tp2", 12, True)
    for bad in (
        {"entry": "stop"},
        {"target": "tp3"},
        {"limit_expiry_bars": 0},
        {"sig_window": "Asia"},
        {"lon_sess": "25:00-0500"},
        {"tz": "Mars/Olympus"},
        {"min_body": -0.1},
        {"pv_l": 0},
        {"sweep_look": 0},
    ):
        with pytest.raises(ValidationError):
            CisdSweepParams.model_validate(bad)


def test_two_runs_give_identical_signals() -> None:
    t = tape(FILL, *SAME_AGAIN, OPPOSITE, level=100.75)
    assert dumps(cisd(t)) == dumps(cisd(t))
    assert dumps(cisd(t, entry="market")) == dumps(cisd(t, entry="market"))

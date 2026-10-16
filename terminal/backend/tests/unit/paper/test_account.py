import decimal
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from kterminal.core.enums import Direction, OrderType, SignalAction
from kterminal.core.ids import uuid7
from kterminal.domain.accounts import AccountSettings
from kterminal.domain.costs import CostCalculator
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.paper.account import InstrumentSetup, PaperAccount
from kterminal.paper.records import DecisionRecord, LedgerRecord, TradeRecord
from tests.fixtures.catalog import lab_catalog

MON = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)  # Monday 09:00 New York: metals open


def account(instance: str = "inst_a", **settings: Any) -> PaperAccount:
    catalog = lab_catalog()
    markets = {}
    for symbol in ("XAUUSD", "XAGUSD"):
        listing = catalog.execution_listing("lab_default", symbol)
        markets[symbol] = InstrumentSetup(
            instrument=catalog.instrument(symbol),
            listing=listing,
            costs=catalog.cost_calculator(listing),
            calendar=catalog.calendar_for(listing),
        )
    return PaperAccount(
        account_id=uuid7(),
        name=f"Paper 50K · {instance}",
        instance_id=instance,
        settings=AccountSettings(**settings),
        config_version_id=uuid7(),
        markets=markets,
        timeframe="5m",
        trading_day_rule=catalog.sessions.trading_day_rule("ny_1700"),
        classify=catalog.sessions.classify,
    )


def signal(
    action: SignalAction,
    at: datetime = MON,
    instance: str = "inst_a",
    symbol: str = "XAUUSD",
    **kw: Any,
) -> Signal:
    fields: dict[str, Any] = {
        "strategy_id": instance,
        "strategy_version": "v1",
        "symbol": symbol,
        "timeframe": "5m",
        "timestamp": at,
        "signal": action,
    }
    fields.update(kw)
    return Signal(**fields)


def bar(at: datetime, o: str, h: str, low: str, c: str, symbol: str = "XAUUSD") -> Bar:
    return Bar.of(symbol, "1m", at, o, h, low, c)


def long_entry(
    entry: str = "4000.00", stop: str = "3995.00", target: str | None = "4010.00", **kw: Any
) -> Signal:
    return signal(
        SignalAction.LONG,
        entry=Decimal(entry),
        stop_loss=Decimal(stop),
        take_profit=Decimal(target) if target else None,
        **kw,
    )


def records(acc: PaperAccount, kind: type) -> list[Any]:
    return [r for r in acc.drain() if isinstance(r, kind)]


def test_sizing_uses_risk_budget_costs_and_rounds_down() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    decision = acc.handle_signal(long_entry(), uuid7(), MON)
    assert decision is not None and decision.approved
    # budget 250 USD; per lot: 5.00 × 100 = 500 + reserve (spread 0.20 + 2 × 0.03 slip) × 100
    # + 2 × 3.50 commission = 533 → 0.469… → 0.46 lots (rounded down)
    assert decision.approved_qty == Decimal("0.46")
    assert decision.risk_pct is not None and decision.risk_pct <= Decimal("0.5")
    assert {r["rule"] for r in decision.rule_results} >= {
        "account_active",
        "market_open",
        "max_open_positions",
        "position_size",
    }


def test_market_entry_fills_next_open_with_spread_slippage_and_commission() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(), uuid7(), MON)
    acc.drain()
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    trade = acc.positions["XAUUSD"].trade
    assert trade.entry_price == Decimal("4000.13")  # 4000.00 + 0.10 half spread + 0.03 slippage
    assert trade.qty == Decimal("0.46")
    assert acc.balance == Decimal("50000") - Decimal("1.61")  # 3.50 × 0.46 commission
    assert trade.session == "ny_session"


def test_take_profit_requires_the_bid_and_books_a_ledgered_trade() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    # mid high 4010.05: bid = 4009.95 < 4010 → target NOT reached
    acc.on_bar(bar(MON + timedelta(minutes=1), "4005.00", "4010.05", "4004.00", "4008.00"))
    assert "XAUUSD" in acc.positions
    acc.on_bar(bar(MON + timedelta(minutes=2), "4008.00", "4010.20", "4007.00", "4009.00"))
    assert "XAUUSD" not in acc.positions
    out = acc.drain()
    closed = [r for r in out if isinstance(r, TradeRecord) and r.status == "CLOSED"]
    (trade,) = closed
    assert trade.exit_reason == "TAKE_PROFIT"
    assert trade.exit_price == Decimal("4010.00")
    gross = (Decimal("4010.00") - Decimal("4000.13")) * Decimal("0.46") * 100
    assert trade.gross_pnl == gross.quantize(Decimal("0.0001"))
    assert trade.net_pnl == trade.gross_pnl - trade.commission
    assert trade.r_multiple is not None and trade.r_multiple > Decimal(1)
    ledger = [r for r in out if isinstance(r, LedgerRecord)]
    assert acc.balance == Decimal(50000) + sum(r.amount for r in ledger)
    assert ledger[-1].balance_after == acc.balance


def test_stop_assumed_first_and_gaps_fill_at_the_open() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    acc.on_bar(bar(MON + timedelta(minutes=1), "3990.00", "4011.00", "3989.00", "4000.00"))
    (trade,) = [r for r in acc.drain() if isinstance(r, TradeRecord) and r.status == "CLOSED"]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price == Decimal("3989.87")  # gap open 3990 − 0.10 − 0.03
    assert trade.r_multiple is not None and trade.r_multiple < Decimal(-1)


def test_stop_level_is_a_bid_price_and_the_spread_is_not_charged_twice() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    # mid low 3995.15: bid 3995.05 > stop 3995.00 → not triggered
    acc.on_bar(bar(MON + timedelta(minutes=1), "4000.00", "4001.00", "3995.15", "3999.00"))
    assert "XAUUSD" in acc.positions
    # mid low 3995.10: bid 3995.00 reaches the stop → fill at the stop − 0.03 slippage
    acc.on_bar(bar(MON + timedelta(minutes=2), "3999.00", "3999.50", "3995.10", "3996.00"))
    (trade,) = [r for r in acc.drain() if isinstance(r, TradeRecord) and r.status == "CLOSED"]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price == Decimal("3994.97")


def test_rejections_are_recorded_with_reasons() -> None:
    acc = account(max_open_positions=1)
    acc.marks["XAUUSD"] = Decimal("4000.00")
    saturday = datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
    closed = acc.handle_signal(long_entry(at=saturday), uuid7(), saturday)
    assert closed is not None and closed.primary_reason == "MARKET_CLOSED"
    tiny = acc.handle_signal(long_entry(stop="1.00"), uuid7(), MON)  # stop 3999 away
    assert tiny is not None and tiny.primary_reason == "SIZE_TOO_SMALL"
    assert acc.handle_signal(long_entry(), uuid7(), MON).approved  # type: ignore[union-attr]
    acc.marks["XAGUSD"] = Decimal("30.000")
    second = acc.handle_signal(
        signal(
            SignalAction.LONG, symbol="XAGUSD", entry=Decimal("30.000"), stop_loss=Decimal("29.500")
        ),
        uuid7(),
        MON,
    )
    assert second is not None and second.primary_reason == "MAX_POSITIONS"
    no_pos = acc.handle_signal(signal(SignalAction.EXIT_SHORT), uuid7(), MON)
    assert no_pos is not None and no_pos.primary_reason == "NO_MATCHING_POSITION"
    assert acc.stats.reject_codes == {
        "MARKET_CLOSED": 1,
        "SIZE_TOO_SMALL": 1,
        "MAX_POSITIONS": 1,
        "NO_MATCHING_POSITION": 1,
    }


def test_signal_from_another_instance_is_refused() -> None:
    acc = account("inst_a")
    with pytest.raises(ValueError, match="refusing a signal from inst_b"):
        acc.handle_signal(long_entry(instance="inst_b"), uuid7(), MON)


def test_move_stop_breakeven_and_no_widening() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    acc.drain()
    entry = acc.positions["XAUUSD"].trade.entry_price
    widen = acc.handle_signal(signal(SignalAction.MOVE_SL, stop_loss=Decimal("3990")), uuid7(), MON)
    assert widen is not None and widen.primary_reason == "STOP_WIDENING_NOT_ALLOWED"
    ok = acc.handle_signal(signal(SignalAction.MOVE_SL, stop_loss=entry), uuid7(), MON)
    assert ok is not None and ok.approved
    events = [r for r in acc.drain() if type(r).__name__ == "TradeEventRecord"]
    assert [e.kind for e in events] == ["BREAKEVEN"]
    acc.on_bar(bar(MON + timedelta(minutes=1), "4000.50", "4000.60", "3999.00", "4000.00"))
    (trade,) = [r for r in acc.drain() if isinstance(r, TradeRecord) and r.status == "CLOSED"]
    assert trade.exit_reason == "BREAKEVEN_STOP"


def test_reversal_exits_then_enters_at_next_open() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(target=None), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    short = signal(SignalAction.SHORT, entry=Decimal("4000.50"), stop_loss=Decimal("4005.00"))
    assert acc.handle_signal(short, uuid7(), MON).approved  # type: ignore[union-attr]
    acc.on_bar(bar(MON + timedelta(minutes=1), "4000.40", "4001.00", "3999.50", "4000.00"))
    assert acc.positions["XAUUSD"].trade.direction is Direction.SHORT
    closed = [r for r in acc.drain() if isinstance(r, TradeRecord) and r.status == "CLOSED"]
    assert [t.exit_reason for t in closed] == ["REVERSAL"]


def test_resting_limit_entry_expires() -> None:
    acc = account()
    limit = long_entry(
        entry="3990.00", stop="3985.00", order_type=OrderType.LIMIT, expires_after_bars=1
    )
    assert acc.handle_signal(limit, uuid7(), MON).approved  # type: ignore[union-attr]
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    assert "XAUUSD" in acc.pending_entries
    acc.on_bar(bar(MON + timedelta(minutes=5), "4000.00", "4001.00", "3999.00", "4000.50"))
    assert "XAUUSD" not in acc.pending_entries
    statuses = [r.status for r in acc.drain() if type(r).__name__ == "OrderRecord"]
    assert statuses[-1] == "EXPIRED"


def test_swap_accrues_overnight_and_lands_in_the_ledger() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(stop="3900.00", target=None), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    acc.drain()
    tuesday = MON + timedelta(days=1)  # crosses the Monday 17:00 New York rollover
    acc.on_bar(bar(tuesday, "4000.50", "4001.00", "3999.50", "4000.50"))
    swaps = [r for r in acc.drain() if isinstance(r, LedgerRecord) and r.kind == "SWAP"]
    assert len(swaps) == 1
    assert swaps[0].amount < 0  # -0.65 × 100 × qty: longs pay
    assert acc.positions["XAUUSD"].swap == swaps[0].amount


def test_equity_marks_and_drawdown() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(stop="3950.00", target=None), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.00"))
    acc.on_bar(bar(MON + timedelta(minutes=1), "4000.00", "4000.00", "3980.00", "3980.00"))
    snap = acc.mark(MON + timedelta(minutes=2))
    assert snap.open_pnl < 0
    assert snap.equity == snap.balance + snap.open_pnl
    assert snap.drawdown == snap.high_water_mark - snap.equity
    assert snap.open_risk > 0


def test_decision_records_account_identity() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    sid: UUID = uuid7()
    decision = acc.handle_signal(long_entry(), sid, MON)
    out = [r for r in acc.drain() if isinstance(r, DecisionRecord)]
    assert out == [decision]
    assert decision is not None
    assert decision.account_id == acc.account_id
    assert decision.account_config_version_id == acc.config_version_id
    assert decision.signal_id == sid


# ── execution realism (review findings) ─────────────────────────────────────
def closed_trades(acc: PaperAccount) -> list[TradeRecord]:
    return [r for r in acc.drain() if isinstance(r, TradeRecord) and r.status == "CLOSED"]


def test_a_bar_opening_beyond_the_target_fills_it_at_the_open() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    # opens at 4015 (bid 4014.90 ≥ target 4010), then trades through the stop: the target
    # came first — it is not a stop-out.
    acc.on_bar(bar(MON + timedelta(minutes=1), "4015.00", "4015.00", "3994.00", "3996.00"))
    (trade,) = closed_trades(acc)
    assert trade.exit_reason == "TAKE_PROFIT"
    assert trade.exit_price == Decimal("4014.90")


def test_after_an_intrabar_limit_fill_only_later_prices_can_reach_the_target() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    limit = long_entry(entry="3990.00", stop="3985.00", order_type=OrderType.LIMIT)
    assert acc.handle_signal(limit, uuid7(), MON).approved  # type: ignore[union-attr]
    # opens at its high (4012 — beyond the 4010 target), falls to fill the limit, closes 3990.50
    acc.on_bar(bar(MON, "4012.00", "4012.00", "3989.50", "3990.50"))
    assert "XAUUSD" in acc.positions  # the high came *before* the fill: no target
    trade = acc.positions["XAUUSD"].trade
    assert trade.entry_price == Decimal("3990.00")
    assert acc.positions["XAUUSD"].best == Decimal("3990.50")  # MFE only from the close


def test_a_limit_the_bar_opens_through_fills_at_the_open() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    limit = long_entry(entry="3990.00", stop="3980.00", order_type=OrderType.LIMIT)
    acc.handle_signal(limit, uuid7(), MON)
    acc.on_bar(bar(MON, "3985.00", "3986.00", "3984.00", "3985.50"))
    assert acc.positions["XAUUSD"].trade.entry_price == Decimal("3985.10")  # the opening ask


def test_a_rejected_reversal_still_exits_the_opposite_position() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    short = signal(
        SignalAction.SHORT, entry=Decimal("4000.50"), stop_loss=Decimal("6000.00")
    )  # its stop is so far away that the size rounds to zero
    decision = acc.handle_signal(short, uuid7(), MON)
    assert decision is not None and decision.primary_reason == "SIZE_TOO_SMALL"
    acc.on_bar(bar(MON + timedelta(minutes=1), "4000.50", "4001.00", "4000.00", "4000.50"))
    (trade,) = closed_trades(acc)
    assert trade.exit_reason == "REVERSAL"
    assert acc.positions == {}


def test_stop_on_the_wrong_side_of_the_market_is_rejected() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")  # the market is 4000 …
    stale = long_entry(entry="4010.00", stop="4005.00", target="4020.00")  # … stop above it
    decision = acc.handle_signal(stale, uuid7(), MON)
    assert decision is not None and decision.primary_reason == "STOP_WRONG_SIDE"


def test_breakeven_is_recognised_at_the_strategys_entry_price() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    acc.drain()
    move = signal(SignalAction.MOVE_SL, stop_loss=Decimal("4000.00"))  # its entry, not the fill
    assert acc.handle_signal(move, uuid7(), MON).approved  # type: ignore[union-attr]
    events = [r for r in acc.drain() if type(r).__name__ == "TradeEventRecord"]
    assert [e.kind for e in events] == ["BREAKEVEN"]
    acc.on_bar(bar(MON + timedelta(minutes=1), "4000.50", "4000.60", "3999.00", "4000.00"))
    (trade,) = closed_trades(acc)
    assert trade.exit_reason == "BREAKEVEN_STOP"


def test_levels_are_put_on_the_listing_grid_against_the_account() -> None:
    acc = account()
    setup = acc.markets["XAUUSD"]
    coarse = replace(setup.listing, tick_size=Decimal("0.10"))
    acc.markets["XAUUSD"] = replace(setup, listing=coarse)
    acc.marks["XAUUSD"] = Decimal("4000.00")
    limit = long_entry(
        entry="3990.05", stop="3985.05", target="4010.05", order_type=OrderType.LIMIT
    )
    acc.handle_signal(limit, uuid7(), MON)
    acc.on_bar(bar(MON, "3995.00", "3996.00", "3989.00", "3990.50"))
    trade = acc.positions["XAUUSD"].trade
    assert trade.entry_price == Decimal("3990.10")  # buy limit: up, never a better price
    assert trade.initial_stop == Decimal("3985.00")  # sell stop: down
    assert trade.initial_target == Decimal("4010.00")  # sell limit: down


def test_money_maths_ignores_the_threads_decimal_context() -> None:
    def run_once() -> tuple[Decimal, Decimal]:
        acc = account()
        acc.marks["XAUUSD"] = Decimal("4000.00")
        acc.handle_signal(long_entry(), uuid7(), MON)
        acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
        acc.on_bar(bar(MON + timedelta(minutes=1), "4008.00", "4010.20", "4007.00", "4009.00"))
        return acc.balance, acc.mark(MON + timedelta(minutes=2)).equity

    expected = run_once()
    with decimal.localcontext() as ctx:
        ctx.prec = 4  # what an in-process strategy could do to the thread
        ctx.rounding = decimal.ROUND_DOWN
        assert run_once() == expected


def test_converted_costs_reconcile_trades_with_the_ledger() -> None:
    catalog = lab_catalog()
    listing = catalog.execution_listing("lab_default", "NEARUSD")  # USDT-quoted perpetual
    acc = PaperAccount(
        account_id=uuid7(),
        name="Paper 50K · inst_a",
        instance_id="inst_a",
        settings=AccountSettings(stablecoin_usd_rate=Decimal("0.99937")),
        config_version_id=uuid7(),
        markets={
            "NEARUSD": InstrumentSetup(
                instrument=catalog.instrument("NEARUSD"),
                listing=listing,
                # notional commission + 8-hourly funding, in USDT
                costs=CostCalculator(
                    catalog.cost_profiles["crypto_perp_binance"], listing, catalog.sessions.labels
                ),
            )
        },
        timeframe="5m",
    )
    acc.marks["NEARUSD"] = Decimal("2.5000")
    entry = signal(
        SignalAction.LONG, symbol="NEARUSD", entry=Decimal("2.5000"), stop_loss=Decimal("2.4500")
    )
    assert acc.handle_signal(entry, uuid7(), MON).approved  # type: ignore[union-attr]
    t = MON
    for price in ("2.5000", "2.5300", "2.5600", "2.5900"):
        acc.on_bar(Bar.of("NEARUSD", "1m", t, price, price, price, price))
        t += timedelta(hours=9)  # crosses funding instants
    acc.close_all(t)
    out = acc.drain()
    (trade,) = [r for r in out if isinstance(r, TradeRecord) and r.status == "CLOSED"]
    ledger = [r for r in out if isinstance(r, LedgerRecord) and r.trade_id == trade.id]
    assert trade.funding != 0
    assert trade.net_pnl == sum(r.amount for r in ledger)
    assert trade.commission == -sum(r.amount for r in ledger if r.kind == "COMMISSION")
    assert trade.funding == sum(r.amount for r in ledger if r.kind == "FUNDING")


def test_resting_entries_expire_after_primary_bars_not_wall_clock() -> None:
    """A 5m order living 3 bars outlives the weekend, exactly like the theoretical book."""
    acc = account()  # primary timeframe 5m
    friday = datetime(2026, 1, 9, 21, 55, tzinfo=UTC)
    sunday = datetime(2026, 1, 11, 23, 0, tzinfo=UTC)
    acc.marks["XAUUSD"] = Decimal("4000.00")
    limit = long_entry(
        entry="3990.00", stop="3980.00", order_type=OrderType.LIMIT, expires_after_bars=3
    )
    assert acc.handle_signal(limit, uuid7(), friday).approved  # type: ignore[union-attr]
    for minute in range(5):  # Fri 21:55-22:00: one 5m bar, not reached
        acc.on_bar(bar(friday + timedelta(minutes=minute), "4000", "4001", "3999", "4000"))
    acc.on_bar(bar(sunday, "3995.00", "3996.00", "3989.00", "3990.50"))  # bar 2: fills
    assert "XAUUSD" in acc.positions


def test_resting_reversal_closes_the_position_only_when_it_fills() -> None:
    acc = account()
    acc.marks["XAUUSD"] = Decimal("4000.00")
    acc.handle_signal(long_entry(target=None), uuid7(), MON)
    acc.on_bar(bar(MON, "4000.00", "4001.00", "3999.00", "4000.50"))
    short_limit = signal(
        SignalAction.SHORT,
        entry=Decimal("4005.00"),
        stop_loss=Decimal("4015.00"),
        order_type=OrderType.LIMIT,
    )
    assert acc.handle_signal(short_limit, uuid7(), MON).approved  # type: ignore[union-attr]
    acc.on_bar(bar(MON + timedelta(minutes=1), "4000.50", "4002.00", "4000.00", "4001.00"))
    assert acc.positions["XAUUSD"].trade.direction is Direction.LONG  # not filled: still long
    acc.on_bar(bar(MON + timedelta(minutes=2), "4001.00", "4006.00", "4000.50", "4004.00"))
    (closed,) = closed_trades(acc)
    assert closed.exit_reason == "REVERSAL" and closed.exit_price == Decimal("4005.00")
    assert acc.positions["XAUUSD"].trade.direction is Direction.SHORT

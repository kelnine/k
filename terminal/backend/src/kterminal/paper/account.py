"""Paper (virtual) account: an independent ledger with simulated execution.

Each strategy instance owns one ``PaperAccount``; accounts share nothing but
the immutable bars they are fed. The account turns its instance's signals into
decisions (checks + risk-based sizing), simulates fills on the **base**
timeframe bars with the venue profile's specification and costs, and keeps a
ledger in which every balance change is an entry.

Execution model (the same for every account, which is what makes lab
comparisons fair):

* entries and signal exits fill at the next base bar's open as market orders:
  half the spread plus slippage against the account, rounded adversely to the
  listing's tick; LIMIT/STOP entries rest until triggered or expired;
* bars are mid prices; a long's stop triggers when the bid reaches it, its
  target when the bid reaches it (short: ask). When one bar reaches both,
  the stop is assumed first. A bar that gaps through a stop fills at the
  (worse) open;
* commissions are charged per fill; funding (perpetuals) and swap (CFD/FX)
  accrue while positions are held; P&L is converted to the account currency.

Phase 2 checks are deliberately basic (market open, one position per
instrument, max open positions, sizing). The full prop-firm rule pipeline
replaces them in Phase 5 without changing this flow.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from kterminal.core.enums import Direction, OrderSide, OrderType, SignalAction
from kterminal.core.ids import uuid7
from kterminal.domain.accounts import AccountSettings
from kterminal.domain.costs import CostCalculator, Liquidity
from kterminal.domain.instruments import CurrencyConversionError, CurrencyRates, Instrument, Listing
from kterminal.domain.market import Bar
from kterminal.domain.sessions import TradingCalendar, TradingDayRule
from kterminal.domain.signals import Signal
from kterminal.paper.records import (
    DecisionRecord,
    EquityRecord,
    FillRecord,
    LedgerRecord,
    OrderRecord,
    Record,
    TradeEventRecord,
    TradeRecord,
)
from kterminal.risk.checks import (
    RuleResult,
    check_max_open_positions,
    check_stop_not_widened,
    failed,
    first_failure,
    passed,
)
from kterminal.risk.sizing import size_position

MONEY = Decimal("0.0001")
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class InstrumentSetup:
    """How an account trades one canonical instrument (from its venue profile)."""

    instrument: Instrument
    listing: Listing
    costs: CostCalculator
    calendar: TradingCalendar | None = None


@dataclass
class _Position:
    trade: TradeRecord
    setup: InstrumentSetup
    accrued_until: datetime
    commission: Decimal = ZERO
    swap: Decimal = ZERO
    funding: Decimal = ZERO
    spread_cost: Decimal = ZERO
    worst: Decimal = ZERO  # most adverse price seen
    best: Decimal = ZERO  # most favourable price seen


@dataclass
class _PendingEntry:
    signal: Signal
    signal_id: UUID
    decision_id: UUID
    order: OrderRecord
    qty: Decimal
    expires_at: datetime | None


@dataclass
class _PendingExit:
    signal: Signal | None
    signal_id: UUID | None
    reason: str
    decision_id: UUID | None = None


@dataclass
class AccountStats:
    signals: int = 0
    approved: int = 0
    rejected: int = 0
    trades_opened: int = 0
    trades_closed: int = 0
    reject_codes: dict[str, int] = field(default_factory=dict)


class PaperAccount:
    def __init__(
        self,
        *,
        account_id: UUID,
        name: str,
        instance_id: str,
        settings: AccountSettings,
        config_version_id: UUID,
        markets: Mapping[str, InstrumentSetup],
        timeframe: str,
        trading_day_rule: TradingDayRule | None = None,
        classify: Callable[[datetime], str] | None = None,
        on_opposite_signal: str = "reverse",
        status: str = "ACTIVE",
    ) -> None:
        self.account_id = account_id
        self.name = name
        self.instance_id = instance_id
        self.settings = settings
        self.config_version_id = config_version_id
        self.markets = dict(markets)
        self.timeframe = timeframe
        self.trading_day_rule = trading_day_rule
        self.classify = classify or (lambda _ts: "unknown")
        self.on_opposite_signal = on_opposite_signal
        self.status = status
        self.rates = CurrencyRates(
            rates=(
                ("USDT", "USD", settings.stablecoin_usd_rate),
                ("USDC", "USD", settings.stablecoin_usd_rate),
            )
        )
        self.balance = settings.starting_balance
        self.high_water_mark = settings.starting_balance
        self.positions: dict[str, _Position] = {}
        self.pending_entries: dict[str, _PendingEntry] = {}
        self.pending_exits: dict[str, _PendingExit] = {}
        self.marks: dict[str, Decimal] = {}
        self.stats = AccountStats()
        self._day: Any = None
        self._day_start_equity = settings.starting_balance
        self._outbox: list[Record] = []

    # ── outbox ──────────────────────────────────────────────────────────────
    def drain(self) -> list[Record]:
        records, self._outbox = self._outbox, []
        return records

    # ── valuation ───────────────────────────────────────────────────────────
    def _fx(self, listing: Listing) -> Decimal:
        return self.rates.rate(listing.quote_currency, self.settings.currency)

    def open_pnl(self) -> Decimal:
        total = ZERO
        for symbol, position in self.positions.items():
            mark = self.marks.get(symbol, position.trade.entry_price)
            trade = position.trade
            pnl = position.setup.listing.pnl(trade.direction, trade.qty, trade.entry_price, mark)
            total += pnl * self._fx(position.setup.listing)
        return total

    def open_risk(self) -> Decimal:
        total = ZERO
        for symbol, position in self.positions.items():
            trade = position.trade
            mark = self.marks.get(symbol, trade.entry_price)
            loss = (
                (mark - trade.current_stop)
                if trade.direction is Direction.LONG
                else (trade.current_stop - mark)
            )
            if loss > 0:
                listing = position.setup.listing
                total += loss * trade.qty * listing.point_value * self._fx(listing)
        return total

    @property
    def equity(self) -> Decimal:
        return self.balance + self.open_pnl()

    def state(self) -> dict[str, Any]:
        """Snapshot recorded with every decision."""
        return {
            "balance": str(self.balance.quantize(MONEY)),
            "equity": str(self.equity.quantize(MONEY)),
            "open_positions": len(self.positions),
            "pending_entries": len(self.pending_entries),
            "open_risk": str(self.open_risk().quantize(MONEY)),
            "status": self.status,
        }

    # ── signals ─────────────────────────────────────────────────────────────
    def handle_signal(self, signal: Signal, signal_id: UUID, at: datetime) -> DecisionRecord | None:
        """Decide on one of this account's own instance's signals."""
        if signal.strategy_id != self.instance_id:
            raise ValueError(
                f"account {self.name} belongs to {self.instance_id}, "
                f"refusing a signal from {signal.strategy_id}"
            )
        if signal.signal is SignalAction.NO_TRADE:
            return None
        self.stats.signals += 1
        setup = self.markets.get(signal.symbol)
        if setup is None:
            return self._decide(
                signal,
                signal_id,
                at,
                [
                    failed(
                        "instrument_available",
                        "SYMBOL_NOT_AVAILABLE",
                        f"{signal.symbol} is not in venue profile {self.settings.venue_profile}",
                    )
                ],
            )
        if signal.signal.is_entry:
            return self._entry(signal, signal_id, at, setup)
        if signal.signal.is_exit:
            return self._exit(signal, signal_id, at)
        return self._move_stop(signal, signal_id, at)

    def _entry(
        self, signal: Signal, signal_id: UUID, at: datetime, setup: InstrumentSetup
    ) -> DecisionRecord:
        direction = signal.signal.direction
        if direction is None or signal.stop_loss is None or signal.entry is None:
            raise ValueError("validated entry signal expected")
        symbol = signal.symbol
        results: list[RuleResult] = []
        results.append(
            passed("account_active")
            if self.status == "ACTIVE"
            else failed("account_active", f"ACCOUNT_{self.status}", f"account is {self.status}")
        )
        listing = setup.listing
        results.append(
            passed("instrument_tradable", listing=listing.key)
            if listing.tradable
            else failed("instrument_tradable", "NOT_TRADABLE", f"{listing.key} is data-only")
        )
        if setup.calendar is not None and not setup.calendar.is_open(at):
            results.append(
                failed(
                    "market_open", "MARKET_CLOSED", f"{listing.key} is closed at {at.isoformat()}"
                )
            )
        else:
            results.append(passed("market_open"))

        reversing = False
        existing = self.positions.get(symbol)
        if existing is not None and existing.trade.direction is direction:
            results.append(
                failed(
                    "one_position_per_instrument",
                    "POSITION_EXISTS",
                    f"already {direction} {symbol}",
                )
            )
        elif existing is not None and self.on_opposite_signal == "ignore":
            results.append(
                failed(
                    "one_position_per_instrument",
                    "OPPOSITE_POSITION_OPEN",
                    f"{existing.trade.direction} {symbol} is open",
                )
            )
        else:
            reversing = existing is not None
            results.append(passed("one_position_per_instrument", reversing=reversing))

        replaced = 1 if symbol in self.pending_entries else 0
        occupied = len(self.positions) + len(self.pending_entries) - replaced - int(reversing)
        results.append(check_max_open_positions(occupied, self.settings.max_open_positions))

        requested_pct = signal.risk if signal.risk is not None else self.settings.risk_per_trade_pct
        risk_pct = min(requested_pct, self.settings.risk_per_trade_pct)
        reference = (
            self.marks.get(symbol, signal.entry)
            if signal.order_type is OrderType.MARKET
            else signal.entry
        )
        try:
            fx = self._fx(listing)
        except CurrencyConversionError as exc:
            results.append(failed("currency", "CURRENCY_CONVERSION", str(exc)))
            return self._decide(signal, signal_id, at, results)
        sizing = size_position(
            equity=self.equity,
            risk_pct=risk_pct,
            entry=reference,
            stop=signal.stop_loss,
            listing=listing,
            fx_rate=fx,
            cost_per_unit=self._cost_reserve(setup, reference, at) * fx,
        )
        if sizing.ok:
            results.append(
                passed(
                    "position_size",
                    qty=sizing.qty,
                    risk_pct=sizing.risk_pct,
                    risk_amount=sizing.actual_risk,
                )
            )
        else:
            results.append(
                failed("position_size", sizing.reject_code or "SIZE_INVALID", sizing.detail)
            )

        decision = self._decide(
            signal,
            signal_id,
            at,
            results,
            requested_qty=sizing.qty,
            risk_amount=sizing.actual_risk,
            risk_pct=sizing.risk_pct,
            quote={"reference": str(reference), "spread": str(setup.costs.spread(at))},
        )
        if not decision.approved:
            return decision

        if reversing and existing is not None:
            self.pending_exits[symbol] = _PendingExit(signal, signal_id, "REVERSAL", decision.id)
        order = OrderRecord(
            id=uuid7(),
            client_order_id=f"{self.instance_id}-{signal_id.hex[:20]}",
            account_id=self.account_id,
            instance_id=self.instance_id,
            purpose="ENTRY",
            venue=listing.venue,
            instrument=symbol,
            venue_symbol=listing.venue_symbol_for(setup.instrument, at.date()),
            side=direction.entry_side,
            order_type=signal.order_type,
            qty=sizing.qty,
            status="ACCEPTED",
            created_at=at,
            correlation_id=signal_id,
            signal_id=signal_id,
            decision_id=decision.id,
            requested_price=reference,
        )
        expires_at = None
        if signal.expires_after_bars is not None:
            expires_at = signal.timestamp + signal.tf.duration * signal.expires_after_bars
        if symbol in self.pending_entries:  # a newer entry replaces a resting one
            self._cancel_pending(symbol, at, "REPLACED")
        self.pending_entries[symbol] = _PendingEntry(
            signal, signal_id, decision.id, order, sizing.qty, expires_at
        )
        self._outbox.append(order)
        return decision

    def _exit(self, signal: Signal, signal_id: UUID, at: datetime) -> DecisionRecord:
        symbol = signal.symbol
        position = self.positions.get(symbol)
        direction = signal.signal.direction
        if position is not None and position.trade.direction is direction:
            decision = self._decide(signal, signal_id, at, [passed("matching_position")])
            self.pending_exits[symbol] = _PendingExit(signal, signal_id, "SIGNAL_EXIT", decision.id)
            return decision
        pending = self.pending_entries.get(symbol)
        if pending is not None and pending.signal.signal.direction is direction:
            decision = self._decide(signal, signal_id, at, [passed("matching_pending_entry")])
            self._cancel_pending(symbol, at, "CANCELLED_BY_EXIT")
            return decision
        return self._decide(
            signal,
            signal_id,
            at,
            [
                failed(
                    "matching_position",
                    "NO_MATCHING_POSITION",
                    f"no {direction} position in {symbol}",
                )
            ],
        )

    def _move_stop(self, signal: Signal, signal_id: UUID, at: datetime) -> DecisionRecord:
        symbol = signal.symbol
        position = self.positions.get(symbol)
        if position is None or signal.stop_loss is None:
            return self._decide(
                signal,
                signal_id,
                at,
                [failed("matching_position", "NO_POSITION", f"no open position in {symbol}")],
            )
        trade = position.trade
        new_stop = position.setup.listing.round_price(signal.stop_loss)
        rule = check_stop_not_widened(
            is_long=trade.direction is Direction.LONG,
            current_stop=trade.current_stop,
            new_stop=new_stop,
        )
        decision = self._decide(signal, signal_id, at, [passed("matching_position"), rule])
        if not decision.approved:
            return decision
        new_target = (
            position.setup.listing.round_price(signal.take_profit)
            if signal.take_profit is not None
            else trade.current_target
        )
        at_entry = new_stop == trade.entry_price
        self._outbox.append(
            TradeEventRecord(
                id=uuid7(),
                trade_id=trade.id,
                ts=at,
                kind="BREAKEVEN" if at_entry else "STOP_MOVED",
                old_value=trade.current_stop,
                new_value=new_stop,
                signal_id=signal_id,
            )
        )
        if new_target != trade.current_target:
            self._outbox.append(
                TradeEventRecord(
                    id=uuid7(),
                    trade_id=trade.id,
                    ts=at,
                    kind="TARGET_MOVED",
                    old_value=trade.current_target,
                    new_value=new_target,
                    signal_id=signal_id,
                )
            )
        position.trade = replace(trade, current_stop=new_stop, current_target=new_target)
        return decision

    def _decide(
        self,
        signal: Signal,
        signal_id: UUID,
        at: datetime,
        results: list[RuleResult],
        *,
        requested_qty: Decimal | None = None,
        risk_amount: Decimal | None = None,
        risk_pct: Decimal | None = None,
        quote: dict[str, Any] | None = None,
    ) -> DecisionRecord:
        failure = first_failure(results)
        approved = failure is None
        if failure is None:
            self.stats.approved += 1
        else:
            self.stats.rejected += 1
            code = failure.code or "REJECTED"
            self.stats.reject_codes[code] = self.stats.reject_codes.get(code, 0) + 1
        decision = DecisionRecord(
            id=uuid7(),
            signal_id=signal_id,
            account_id=self.account_id,
            account_config_version_id=self.config_version_id,
            decided_at=at,
            approved=approved,
            primary_reason=None if failure is None else failure.code,
            rule_results=[r.document() for r in results],
            account_state=self.state(),
            quote=quote or {},
            requested_qty=requested_qty,
            approved_qty=requested_qty if approved else None,
            risk_amount=risk_amount,
            risk_pct=risk_pct,
        )
        self._outbox.append(decision)
        return decision

    def _cost_reserve(self, setup: InstrumentSetup, price: Decimal, at: datetime) -> Decimal:
        """Expected round-trip spread + slippage + commission per 1.0 quantity (quote ccy)."""
        costs = setup.costs
        listing = setup.listing
        price_cost = costs.spread(at) + 2 * costs.slippage(price, at)
        commission = 2 * costs.commission(Decimal(1), price) if price > 0 else ZERO
        return price_cost * listing.point_value + commission

    # ── bars ────────────────────────────────────────────────────────────────
    def on_bar(self, bar: Bar) -> None:
        """Process one closed base-timeframe bar of an instrument this account trades."""
        symbol = bar.instrument
        setup = self.markets.get(symbol)
        if setup is None:
            return
        self._roll_day(bar.open_time)
        position = self.positions.get(symbol)
        if position is not None:
            self._accrue(position, bar.open_time, bar.open)

        pending_exit = self.pending_exits.pop(symbol, None)
        if pending_exit is not None and symbol in self.positions:
            self._close_market(self.positions[symbol], bar.open, bar.open_time, pending_exit)

        pending = self.pending_entries.get(symbol)
        if pending is not None and symbol not in self.positions:
            if pending.expires_at is not None and bar.open_time >= pending.expires_at:
                self._cancel_pending(symbol, bar.open_time, "EXPIRED")
            else:
                self._try_entry(pending, setup, bar)

        position = self.positions.get(symbol)
        if position is not None:
            # Intrabar timing is unknown: the bar's range counts toward excursions and
            # holding costs accrue to its close before a bracket exit is booked there.
            self._track_excursion(position, bar)
            self._accrue(position, bar.close_time, bar.close)
            self._check_brackets(position, bar)
        self.marks[symbol] = bar.close

    def _try_entry(self, pending: _PendingEntry, setup: InstrumentSetup, bar: Bar) -> None:
        signal = pending.signal
        direction = signal.signal.direction
        if direction is None or signal.stop_loss is None:
            raise ValueError("validated entry signal expected")
        side = direction.entry_side
        costs = setup.costs
        at = bar.open_time
        if signal.order_type is OrderType.MARKET:
            fill = costs.market_fill(side, bar.open, at)
            price, half_spread, slip = fill.price, fill.half_spread, fill.slippage
            liquidity = Liquidity.TAKER
        else:
            level = signal.entry
            if level is None:
                raise ValueError("resting entry without price")
            if signal.order_type is OrderType.LIMIT:
                if not costs.limit_triggered(side, level, bar.high, bar.low, at):
                    return
                price, half_spread, slip = costs.limit_fill_price(side, level), ZERO, ZERO
                liquidity = Liquidity.MAKER
            else:
                if not costs.stop_triggered(side, level, bar.high, bar.low, at):
                    return
                trigger = max(bar.open, level) if side is OrderSide.BUY else min(bar.open, level)
                fill = costs.stop_fill(side, trigger, at)
                price, half_spread, slip = fill.price, fill.half_spread, fill.slippage
                liquidity = Liquidity.TAKER
        self.pending_entries.pop(signal.symbol, None)
        self._open(pending, setup, price, half_spread, slip, liquidity, at)

    def _open(
        self,
        pending: _PendingEntry,
        setup: InstrumentSetup,
        price: Decimal,
        half_spread: Decimal,
        slippage: Decimal,
        liquidity: Liquidity,
        at: datetime,
    ) -> None:
        signal = pending.signal
        listing = setup.listing
        direction = signal.signal.direction
        stop = signal.stop_loss
        if direction is None or stop is None:
            raise ValueError("validated entry signal expected")
        fx = self._fx(listing)
        qty = pending.qty
        commission = setup.costs.commission(qty, price, liquidity) * fx
        initial_risk = abs(price - stop) * qty * listing.point_value * fx
        trade_id = uuid7()
        fill = FillRecord(
            id=uuid7(),
            order_id=pending.order.id,
            account_id=self.account_id,
            ts=at,
            qty=qty,
            price=price,
            commission=commission,
            liquidity=liquidity.value,
            spread_cost=(half_spread * qty * listing.point_value * fx).quantize(MONEY),
            slippage=slippage,
        )
        trade = TradeRecord(
            id=trade_id,
            account_id=self.account_id,
            account_config_version_id=self.config_version_id,
            instance_id=self.instance_id,
            strategy_version=signal.strategy_version,
            entry_signal_id=pending.signal_id,
            mode=self.settings.mode.value,
            instrument=signal.symbol,
            venue=listing.venue,
            venue_symbol=pending.order.venue_symbol,
            timeframe=self.timeframe,
            direction=direction,
            qty=qty,
            entry_requested=pending.order.requested_price or price,
            entry_price=price,
            entry_time=at,
            initial_stop=stop,
            initial_target=signal.take_profit,
            current_stop=stop,
            current_target=signal.take_profit,
            initial_risk=initial_risk.quantize(MONEY),
            status="OPEN",
            correlation_id=pending.signal_id,
            session=self.classify(at),
            entry_slippage=slippage,
        )
        self._outbox.append(
            replace(
                pending.order,
                trade_id=trade_id,
                status="FILLED",
                completed_at=at,
                filled_qty=qty,
                avg_fill_price=price,
                slippage=slippage,
                commission=commission,
            )
        )
        self._outbox.append(fill)
        self._ledger(at, "COMMISSION", -commission, trade_id, fill.id, "entry commission")
        self.positions[signal.symbol] = _Position(
            trade=trade,
            setup=setup,
            accrued_until=at,
            commission=commission,
            spread_cost=fill.spread_cost,
            worst=price,
            best=price,
        )
        self.stats.trades_opened += 1
        self._outbox.append(trade)

    def _check_brackets(self, position: _Position, bar: Bar) -> None:
        trade = position.trade
        costs = position.setup.costs
        at = bar.close_time  # intrabar timing is unknown; book it at the bar's close
        exit_side = trade.direction.exit_side
        if costs.stop_triggered(exit_side, trade.current_stop, bar.high, bar.low, bar.open_time):
            if trade.direction is Direction.LONG:
                trigger = min(bar.open, trade.current_stop)
            else:
                trigger = max(bar.open, trade.current_stop)
            fill = costs.stop_fill(exit_side, trigger, bar.open_time)
            self._close(
                position,
                fill.price,
                at,
                self._stop_reason(trade),
                "STOP_LOSS",
                fill.half_spread,
                fill.slippage,
                Liquidity.TAKER,
                None,
            )
            return
        target = trade.current_target
        if target is not None and costs.limit_triggered(
            exit_side, target, bar.high, bar.low, bar.open_time
        ):
            self._close(
                position,
                costs.limit_fill_price(exit_side, target),
                at,
                "TAKE_PROFIT",
                "TAKE_PROFIT",
                ZERO,
                ZERO,
                Liquidity.MAKER,
                None,
            )

    @staticmethod
    def _stop_reason(trade: TradeRecord) -> str:
        if trade.current_stop == trade.initial_stop:
            return "STOP_LOSS"
        beyond_entry = (
            (trade.current_stop > trade.entry_price)
            if trade.direction is Direction.LONG
            else (trade.current_stop < trade.entry_price)
        )
        if trade.current_stop == trade.entry_price:
            return "BREAKEVEN_STOP"
        return "TRAILING_STOP" if beyond_entry else "STOP_LOSS"

    def _close_market(
        self, position: _Position, mid: Decimal, at: datetime, pending: _PendingExit
    ) -> None:
        side = position.trade.direction.exit_side
        fill = position.setup.costs.market_fill(side, mid, at)
        self._close(
            position,
            fill.price,
            at,
            pending.reason,
            "EXIT",
            fill.half_spread,
            fill.slippage,
            Liquidity.TAKER,
            pending.signal_id,
        )

    def _close(
        self,
        position: _Position,
        price: Decimal,
        at: datetime,
        reason: str,
        purpose: str,
        half_spread: Decimal,
        slippage: Decimal,
        liquidity: Liquidity,
        exit_signal_id: UUID | None,
    ) -> None:
        trade = position.trade
        listing = position.setup.listing
        fx = self._fx(listing)
        commission = position.setup.costs.commission(trade.qty, price, liquidity) * fx
        order = OrderRecord(
            id=uuid7(),
            client_order_id=f"{self.instance_id}-{uuid7().hex[:20]}",
            account_id=self.account_id,
            instance_id=self.instance_id,
            purpose=purpose,
            venue=listing.venue,
            instrument=trade.instrument,
            venue_symbol=trade.venue_symbol,
            side=trade.direction.exit_side,
            order_type=OrderType.LIMIT
            if purpose == "TAKE_PROFIT"
            else (OrderType.STOP if purpose == "STOP_LOSS" else OrderType.MARKET),
            qty=trade.qty,
            status="FILLED",
            created_at=at,
            correlation_id=trade.correlation_id,
            trade_id=trade.id,
            signal_id=exit_signal_id,
            completed_at=at,
            filled_qty=trade.qty,
            avg_fill_price=price,
            slippage=slippage,
            commission=commission,
            requested_price=trade.current_stop
            if purpose == "STOP_LOSS"
            else (trade.current_target if purpose == "TAKE_PROFIT" else None),
        )
        fill = FillRecord(
            id=uuid7(),
            order_id=order.id,
            account_id=self.account_id,
            ts=at,
            qty=trade.qty,
            price=price,
            commission=commission,
            liquidity=liquidity.value,
            spread_cost=(half_spread * trade.qty * listing.point_value * fx).quantize(MONEY),
            slippage=slippage,
        )
        gross = listing.pnl(trade.direction, trade.qty, trade.entry_price, price) * fx
        total_commission = position.commission + commission
        net = gross - total_commission + position.swap + position.funding
        r_multiple = (net / trade.initial_risk).quantize(MONEY) if trade.initial_risk else None
        self._outbox.extend((order, fill))
        self._ledger(at, "COMMISSION", -commission, trade.id, fill.id, "exit commission")
        self._ledger(at, "REALIZED_PNL", gross, trade.id, fill.id, f"{reason.lower()} exit")
        sign = 1 if trade.direction is Direction.LONG else -1
        closed = replace(
            trade,
            status="CLOSED",
            exit_signal_id=exit_signal_id,
            exit_price=price,
            exit_time=at,
            exit_reason=reason,
            gross_pnl=gross.quantize(MONEY),
            commission=total_commission.quantize(MONEY),
            swap=position.swap.quantize(MONEY),
            funding=position.funding.quantize(MONEY),
            net_pnl=net.quantize(MONEY),
            r_multiple=r_multiple,
            exit_slippage=slippage,
            spread_cost=(position.spread_cost + fill.spread_cost).quantize(MONEY),
            mae=(trade.entry_price - position.worst) * sign,
            mfe=(position.best - trade.entry_price) * sign,
        )
        del self.positions[trade.instrument]
        self.stats.trades_closed += 1
        self._outbox.append(closed)

    def _accrue(self, position: _Position, until: datetime, mark: Decimal) -> None:
        if until <= position.accrued_until:
            return
        trade = position.trade
        costs = position.setup.costs
        fx = self._fx(position.setup.listing)
        start = position.accrued_until
        for event in [
            *costs.funding_events(trade.direction, trade.qty, mark, start, until),
            *costs.swap_events(trade.direction, trade.qty, mark, start, until),
        ]:
            amount = event.amount * fx
            if event.kind == "FUNDING":
                position.funding += amount
            else:
                position.swap += amount
            self._ledger(event.ts, str(event.kind), amount, trade.id, None, event.detail[:200])
        position.accrued_until = until

    def _track_excursion(self, position: _Position, bar: Bar) -> None:
        if position.trade.direction is Direction.LONG:
            position.worst = min(position.worst, bar.low)
            position.best = max(position.best, bar.high)
        else:
            position.worst = max(position.worst, bar.high)
            position.best = min(position.best, bar.low)

    def _cancel_pending(self, symbol: str, at: datetime, reason: str) -> None:
        pending = self.pending_entries.pop(symbol, None)
        if pending is None:
            return
        status = "EXPIRED" if reason == "EXPIRED" else "CANCELLED"
        self._outbox.append(
            replace(pending.order, status=status, completed_at=at, reject_reason=reason)
        )

    def _ledger(
        self,
        at: datetime,
        kind: str,
        amount: Decimal,
        trade_id: UUID | None,
        fill_id: UUID | None,
        note: str,
    ) -> None:
        amount = amount.quantize(MONEY)
        if amount == 0 and kind != "REALIZED_PNL":
            return
        self.balance += amount
        self._outbox.append(
            LedgerRecord(
                id=uuid7(),
                account_id=self.account_id,
                ts=at,
                kind=kind,
                amount=amount,
                balance_after=self.balance,
                trade_id=trade_id,
                fill_id=fill_id,
                note=note,
            )
        )

    # ── time ────────────────────────────────────────────────────────────────
    def _roll_day(self, at: datetime) -> None:
        if self.trading_day_rule is None:
            return
        day = self.trading_day_rule.trading_day(at)
        if day != self._day:
            self._day = day
            self._day_start_equity = self.equity

    def mark(self, at: datetime) -> EquityRecord:
        """Record an equity snapshot at ``at`` (mark-to-market at the last bar closes)."""
        equity = self.equity
        self.high_water_mark = max(self.high_water_mark, equity)
        record = EquityRecord(
            account_id=self.account_id,
            ts=at,
            balance=self.balance.quantize(MONEY),
            equity=equity.quantize(MONEY),
            open_pnl=self.open_pnl().quantize(MONEY),
            open_risk=self.open_risk().quantize(MONEY),
            daily_pnl=(equity - self._day_start_equity).quantize(MONEY),
            drawdown=(self.high_water_mark - equity).quantize(MONEY),
            high_water_mark=self.high_water_mark.quantize(MONEY),
        )
        self._outbox.append(record)
        return record

    def close_all(self, at: datetime, reason: str = "RUN_END") -> None:
        """Flatten every open position at the last marks (used at the end of a simulation)."""
        for symbol in list(self.positions):
            position = self.positions[symbol]
            mark = self.marks.get(symbol, position.trade.entry_price)
            self._accrue(position, at, mark)
            self._close_market(position, mark, at, _PendingExit(None, None, reason))
        for symbol in list(self.pending_entries):
            self._cancel_pending(symbol, at, reason)


def snapshot_due(last: datetime | None, now: datetime, every: timedelta) -> bool:
    return last is None or now - last >= every

"""
Orchestrates the paper-trading lifecycle:
  1. Receive a confirmed signal
  2. Size the position via RiskManager
  3. Get a live quote from the broker
  4. Place the paper order
  5. Monitor open positions for SL/TP and trailing
"""
import logging
import uuid
from datetime import datetime

from config import BROKER, LIVE_TRADING, TRAIL_AFTER_TP1
from bot.brokers.base import BaseBroker
from bot.brokers.tradier import TradierBroker
from bot.brokers.alpaca import AlpacaBroker
from bot.risk_manager import RiskManager
from bot.state import Position, TradingState

logger = logging.getLogger(__name__)


def _make_broker() -> BaseBroker:
    if BROKER == "alpaca":
        logger.info("Using Alpaca broker (paper mode)")
        return AlpacaBroker()
    logger.info("Using Tradier broker (sandbox mode)")
    return TradierBroker()


class PaperTrader:
    def __init__(self):
        self.broker = _make_broker()
        self.risk = RiskManager()

    async def enter_trade(self, signal: dict, state: TradingState) -> Position | None:
        """
        Attempt to enter a paper trade for the given signal.
        Returns the Position if successful, None otherwise.
        """
        assert not LIVE_TRADING, "LIVE_TRADING must be False"

        ticker = signal["ticker"]
        option_type = signal["option_type"]
        strike = signal["strike"]
        expiry = signal["expiry"]
        dte = signal["dte"]

        option_symbol = BaseBroker.build_option_symbol(ticker, expiry, option_type, strike)

        # Get live quote
        quote = await self.broker.get_option_quote(option_symbol)
        if not quote:
            logger.warning(f"Could not get quote for {option_symbol}, skipping trade.")
            return None

        entry_price = quote.get("ask") or quote.get("mid") or quote.get("last")
        if not entry_price or entry_price <= 0:
            logger.warning(f"Invalid entry price {entry_price} for {option_symbol}")
            return None

        contracts = self.risk.calculate_contracts(state.balance, entry_price)
        if contracts <= 0:
            logger.warning(f"Zero contracts calculated for {ticker}, skipping.")
            return None

        entry_cost = contracts * entry_price * 100
        if entry_cost > state.balance:
            logger.warning(
                f"Entry cost ${entry_cost:.2f} > balance ${state.balance:.2f}, skipping."
            )
            return None

        stop_loss = self.risk.stop_loss_price(entry_price)
        tp1 = self.risk.tp1_price(entry_price)
        tp2 = self.risk.tp2_price(entry_price)

        # Place paper order
        order = await self.broker.place_option_order(
            underlying=ticker,
            option_symbol=option_symbol,
            side="buy_to_open",
            contracts=contracts,
            order_type="market",
            limit_price=None,
        )
        if order is None:
            logger.error(f"Broker rejected order for {option_symbol}")
            return None

        broker_order_id = str(order.get("id") or order.get("order_id") or "")

        position = Position(
            trade_id=str(uuid.uuid4())[:8],
            ticker=ticker,
            option_symbol=option_symbol,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            dte_at_entry=dte,
            contracts=contracts,
            entry_price=entry_price,
            entry_cost=entry_cost,
            entry_time=datetime.utcnow().isoformat(),
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=tp2,
            tp1_hit=False,
            trail_stop=None,
            broker_order_id=broker_order_id,
            flow_side=option_type,
            signal_premium=signal["premium"],
        )

        state.open_position(position)
        logger.info(
            f"Paper trade opened: {ticker} {option_type.upper()} "
            f"${strike} exp {expiry} | {contracts}x @ ${entry_price:.4f} | "
            f"SL=${stop_loss:.4f} TP1=${tp1:.4f} TP2=${tp2:.4f}"
        )
        return position

    async def check_positions(self, state: TradingState) -> list:
        """
        Check all open positions for SL/TP hits.
        Returns a list of ClosedTrade objects for any positions that were closed.
        """
        closed_trades = []
        for trade_id, pos in list(state.positions.items()):
            try:
                quote = await self.broker.get_option_quote(pos.option_symbol)
                if not quote:
                    continue

                current_price = quote.get("last") or quote.get("mid") or 0
                if current_price <= 0:
                    continue

                exit_reason, exit_price = self.risk.check_exit(
                    entry_price=pos.entry_price,
                    current_price=current_price,
                    stop_loss=pos.stop_loss,
                    tp1=pos.tp1,
                    tp2=pos.tp2,
                    tp1_hit=pos.tp1_hit,
                    trail_stop=pos.trail_stop,
                )

                if exit_reason == "TP1" and not pos.tp1_hit:
                    # Hit TP1: record it, start trailing, don't close yet
                    state.update_position_tp1_hit(trade_id)
                    if TRAIL_AFTER_TP1:
                        trail = self.risk.trail_stop_price(current_price)
                        state.update_trail_stop(trade_id, trail)
                        logger.info(
                            f"TP1 hit on {pos.ticker} @ ${current_price:.4f}. "
                            f"Trail stop set to ${trail:.4f}"
                        )
                    continue

                if exit_reason in ("TP2", "SL", "TRAIL"):
                    # Close the position
                    order = await self.broker.place_option_order(
                        underlying=pos.ticker,
                        option_symbol=pos.option_symbol,
                        side="sell_to_close",
                        contracts=pos.contracts,
                        order_type="market",
                        limit_price=None,
                    )
                    if order is None:
                        logger.error(f"Failed to close {pos.option_symbol}")
                        continue

                    closed = state.close_position(trade_id, current_price, exit_reason)
                    if closed:
                        closed_trades.append(closed)

                elif pos.tp1_hit and TRAIL_AFTER_TP1:
                    # Update trailing stop as price moves up
                    new_trail = self.risk.trail_stop_price(current_price)
                    if pos.trail_stop is None or new_trail > pos.trail_stop:
                        state.update_trail_stop(trade_id, new_trail)

            except Exception as exc:
                logger.error(f"Error checking position {trade_id}: {exc}", exc_info=True)

        return closed_trades

    async def close_all_eod(self, state: TradingState) -> list:
        """Force-close all remaining positions at end of day."""
        closed_trades = []
        for trade_id, pos in list(state.positions.items()):
            quote = await self.broker.get_option_quote(pos.option_symbol)
            exit_price = (quote.get("last") or quote.get("mid") or pos.entry_price) if quote else pos.entry_price

            order = await self.broker.place_option_order(
                underlying=pos.ticker,
                option_symbol=pos.option_symbol,
                side="sell_to_close",
                contracts=pos.contracts,
                order_type="market",
                limit_price=None,
            )
            if order:
                closed = state.close_position(trade_id, exit_price, "EOD")
                if closed:
                    closed_trades.append(closed)
        return closed_trades

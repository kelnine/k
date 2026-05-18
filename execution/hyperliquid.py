"""Hyperliquid perpetual futures execution adapter.

DISABLED BY DEFAULT.
To enable:
  1. Set config.execution.hyperliquid.enabled = true
  2. Set environment variables:
       HYPERLIQUID_PRIVATE_KEY   — EVM private key (hex, no 0x prefix)
       HYPERLIQUID_WALLET_ADDRESS — corresponding wallet address
  3. Start with mode: live in config/settings.yaml

Never commit private keys. Never enable on paper-trading sessions.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from risk.engine import TradeParams

logger = logging.getLogger(__name__)

_SDK_AVAILABLE = False
try:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.utils import constants as hl_constants
    import eth_account
    _SDK_AVAILABLE = True
except ImportError:
    pass


class HyperliquidAdapter:
    """Live execution adapter for Hyperliquid DEX perpetual futures.

    All methods are no-ops (raise RuntimeError) when disabled.
    """

    def __init__(self, config: dict) -> None:
        hl_cfg = config.get("execution", {}).get("hyperliquid", {})
        self._enabled: bool = bool(hl_cfg.get("enabled", False))
        self._testnet: bool = bool(hl_cfg.get("testnet", True))
        self._slippage: float = float(hl_cfg.get("slippage_tolerance", 0.001))
        self._exchange: Optional[object] = None
        self._info: Optional[object] = None

        if self._enabled:
            self._initialize()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def place_order(self, params: TradeParams) -> dict:
        self._require_enabled()
        coin = self._to_coin(params.symbol)
        is_buy = params.direction == "long"
        qty = params.size_usd * params.leverage / params.entry_price

        logger.warning(
            f"[LIVE] Placing {params.direction.upper()} {coin} "
            f"qty={qty:.4f} | entry≈{params.entry_price:.4f} "
            f"| SL={params.stop_loss:.4f} | lev={params.leverage}x"
        )

        result = self._exchange.order(  # type: ignore[union-attr]
            coin,
            is_buy,
            round(qty, 6),
            params.entry_price,
            {"limit": {"tif": "Ioc"}},  # IOC approximates a market fill
        )

        if isinstance(result, dict) and result.get("status") == "ok":
            self._place_sl(coin, params, qty)

        return result or {}

    def get_balance(self) -> float:
        self._require_enabled()
        wallet = os.environ.get("HYPERLIQUID_WALLET_ADDRESS", "")
        state = self._info.user_state(wallet)  # type: ignore[union-attr]
        return float(state.get("marginSummary", {}).get("accountValue", 0))

    def get_positions(self) -> list:
        self._require_enabled()
        wallet = os.environ.get("HYPERLIQUID_WALLET_ADDRESS", "")
        state = self._info.user_state(wallet)  # type: ignore[union-attr]
        return state.get("assetPositions", [])

    def cancel_all(self, symbol: str) -> None:
        self._require_enabled()
        coin = self._to_coin(symbol)
        open_orders = self._info.open_orders(  # type: ignore[union-attr]
            os.environ.get("HYPERLIQUID_WALLET_ADDRESS", "")
        )
        for order in open_orders:
            if order.get("coin") == coin:
                self._exchange.cancel(coin, order["oid"])  # type: ignore[union-attr]

    # ── Private ───────────────────────────────────────────────────────────────

    def _initialize(self) -> None:
        if not _SDK_AVAILABLE:
            raise RuntimeError(
                "hyperliquid-python-sdk and eth-account are required for live trading.\n"
                "Install: pip install hyperliquid-python-sdk eth-account"
            )

        private_key = os.environ.get("HYPERLIQUID_PRIVATE_KEY")
        wallet_address = os.environ.get("HYPERLIQUID_WALLET_ADDRESS")

        if not private_key:
            raise RuntimeError("HYPERLIQUID_PRIVATE_KEY environment variable is not set")
        if not wallet_address:
            raise RuntimeError("HYPERLIQUID_WALLET_ADDRESS environment variable is not set")

        net = "TESTNET" if self._testnet else "MAINNET"
        base_url = (
            hl_constants.TESTNET_API_URL if self._testnet else hl_constants.MAINNET_API_URL
        )
        account = eth_account.Account.from_key(private_key)

        self._info = Info(base_url, skip_ws=True)
        self._exchange = Exchange(account, base_url)

        logger.warning(
            f"[LIVE] Hyperliquid adapter connected — {net} | "
            f"wallet={wallet_address[:8]}…{wallet_address[-4:]}"
        )

    def _place_sl(self, coin: str, params: TradeParams, qty: float) -> None:
        is_buy = params.direction == "short"  # SL closes position (opposite direction)
        try:
            self._exchange.order(  # type: ignore[union-attr]
                coin,
                is_buy,
                round(qty, 6),
                params.stop_loss,
                {
                    "trigger": {
                        "triggerPx": params.stop_loss,
                        "isMarket": True,
                        "tpsl": "sl",
                    }
                },
            )
            logger.info(f"[LIVE] SL order placed @ {params.stop_loss:.4f}")
        except Exception as exc:
            logger.error(f"[LIVE] Failed to place SL order: {exc}")

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise RuntimeError(
                "HyperliquidAdapter is disabled. "
                "Set execution.hyperliquid.enabled=true and provide credentials."
            )

    @staticmethod
    def _to_coin(symbol: str) -> str:
        return symbol.replace("-PERP", "").replace("/USDT:USDT", "")

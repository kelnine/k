"""Configuration loaded from environment. See .env.example."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val or ""


@dataclass
class Config:
    # --- Telegram ---
    bot_token: str = field(default_factory=lambda: _get("BOT_TOKEN", required=True))
    # Public free channel: @handle or numeric id (e.g. -1001234567890)
    free_channel: str = field(default_factory=lambda: _get("FREE_CHANNEL", required=True))
    # Private VIP channel the bot owns and adds paying users to
    vip_channel: str = field(default_factory=lambda: _get("VIP_CHANNEL", ""))
    # Admin user ids allowed to run /post, /stats (comma separated)
    admin_ids: tuple[int, ...] = field(
        default_factory=lambda: tuple(
            int(x) for x in _get("ADMIN_IDS", "").replace(" ", "").split(",") if x
        )
    )

    # --- Monetization ---
    # Exchange referral code (the analysis engine returns one, e.g. NMX8B0ND)
    ref_code: str = field(default_factory=lambda: _get("REF_CODE", "NMX8B0ND"))
    # Referral landing links per exchange. {ref} is substituted with ref_code.
    ref_links: dict = field(
        default_factory=lambda: {
            "WEEX": _get("REF_WEEX", "https://weex.com/register?ref={ref}"),
            "Bitunix": _get("REF_BITUNIX", "https://www.bitunix.com/register?ref={ref}"),
            "BTCC": _get("REF_BTCC", "https://www.btcc.com/register?ref={ref}"),
        }
    )
    # VIP price in Telegram Stars (XTR). ~ $0.013/Star, so 2000 ≈ $26.
    vip_price_stars: int = field(default_factory=lambda: int(_get("VIP_PRICE_STARS", "2000")))
    vip_days: int = field(default_factory=lambda: int(_get("VIP_DAYS", "30")))

    # --- Signal generation ---
    # Comma-separated symbols to scan, e.g. BTC,ETH,SOL,ZEC
    watchlist: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            s.strip().upper()
            for s in _get("WATCHLIST", "BTC,ETH,SOL,ZEC,SUI,LINK").split(",")
            if s.strip()
        )
    )
    # Min confidence (0-100) to post a free signal; VIP gets a lower bar.
    free_min_confidence: int = field(default_factory=lambda: int(_get("FREE_MIN_CONFIDENCE", "55")))
    vip_min_confidence: int = field(default_factory=lambda: int(_get("VIP_MIN_CONFIDENCE", "45")))
    # Minutes between scheduled scans.
    post_interval_min: int = field(default_factory=lambda: int(_get("POST_INTERVAL_MIN", "120")))
    # Timezone label shown on posts (cosmetic, matches the reference screenshot).
    tz_label: str = field(default_factory=lambda: _get("TZ_LABEL", "UTC"))

    # --- Data source ---
    # "binance" (zero-config public data) or "liquid" (Co-Invest engine).
    data_source: str = field(default_factory=lambda: _get("DATA_SOURCE", "binance"))
    liquid_base_url: str = field(default_factory=lambda: _get("LIQUID_BASE_URL", ""))
    liquid_token: str = field(default_factory=lambda: _get("LIQUID_TOKEN", ""))

    db_path: str = field(default_factory=lambda: _get("DB_PATH", "signals.db"))

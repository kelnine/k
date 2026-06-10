"""Render a Signal as a Telegram message — styled after the reference channel,
with our referral footer and (for free posts) a VIP upsell."""
from __future__ import annotations

from datetime import datetime, timezone

from .config import Config
from .strategy import Signal

_SIDE_EMOJI = {"LONG": "🟢", "SHORT": "🔴"}


def _ref_footer(cfg: Config) -> str:
    parts = []
    for name, tmpl in cfg.ref_links.items():
        url = tmpl.replace("{ref}", cfg.ref_code)
        parts.append(f'<a href="{url}">{name}</a>')
    return "Trade with us (referral links):\n" + " | ".join(parts)


def render(sig: Signal, cfg: Config, *, tier: str = "free") -> str:
    """tier: 'free' (teaser, hides TP2 + upsell) or 'vip' (full)."""
    emoji = _SIDE_EMOJI.get(sig.side, "⚪")
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")

    lines = [
        f"{emoji} <b>{sig.side} SIGNAL — {sig.symbol}/USDT</b>",
        f"🧠 Strategy: {sig.strategy}",
        f"⚡ Triggers: {' | '.join(sig.triggers)}",
        "",
        f"🎯 Confidence: {sig.confidence}%",
        f"⚙️ Leverage: {sig.leverage}x (isolated)",
        f"🏁 Entry: ${_fmt(sig.entry)}",
        f"🛑 Stop Loss: ${_fmt(sig.stop_loss)}",
        f"🎯 TP1: ${_fmt(sig.tp1)}",
    ]

    if tier == "vip":
        lines.append(f"🎯 TP2: ${_fmt(sig.tp2)}")
        lines.append(f"📐 R:R ≈ {sig.rr:.1f}")
    else:
        lines.append("🎯 TP2: 🔒 VIP")
        lines.append("📐 Full targets + sizing → /vip")

    lines += [
        "",
        f"🕒 {now} ({cfg.tz_label})",
        "⚠️ Disclaimer (NFA): Futures trading involves a high level of risk "
        "and may not be suitable for all investors. Not financial advice.",
        "",
        _ref_footer(cfg),
    ]
    return "\n".join(lines)


def _fmt(x: float) -> str:
    if x >= 1000:
        return f"{x:,.1f}"
    if x >= 1:
        return f"{x:,.2f}"
    return f"{x:.6f}".rstrip("0").rstrip(".")

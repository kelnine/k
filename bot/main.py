"""Telegram signal bot.

- Scans the watchlist on a schedule, generates signals from the analysis
  engine, posts teasers to the free channel and full signals to the VIP channel.
- Sells VIP access via Telegram Stars (native payments, no merchant account).
- Tracks every call and posts a weekly win-rate to build trust.

Run:  python -m bot.main
"""
from __future__ import annotations

import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
)

from .config import Config
from .datasources import build_data_source
from .formatter import render
from .store import Store
from .strategy import generate

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s", level=logging.INFO
)
log = logging.getLogger("signalbot")


# --------------------------------------------------------------------------
# Core: scan + post
# --------------------------------------------------------------------------
async def scan_and_post(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.application.bot_data["cfg"]
    store: Store = context.application.bot_data["store"]
    src = context.application.bot_data["src"]

    posted = 0
    for symbol in cfg.watchlist:
        snap = src.snapshot(symbol)
        if not snap:
            continue
        sig = generate(snap)
        if not sig:
            continue

        if sig.confidence >= cfg.free_min_confidence:
            store.log_call(sig, "free")
            await context.bot.send_message(
                cfg.free_channel,
                render(sig, cfg, tier="free"),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            posted += 1

        if cfg.vip_channel and sig.confidence >= cfg.vip_min_confidence:
            await context.bot.send_message(
                cfg.vip_channel,
                render(sig, cfg, tier="vip"),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

    log.info("scan complete: %d free posts", posted)


async def post_weekly_stats(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.application.bot_data["cfg"]
    store: Store = context.application.bot_data["store"]
    s = store.record_stats(7)
    if s["total"] == 0:
        return
    msg = (
        f"📊 <b>7-day track record</b>\n"
        f"Calls closed: {s['total']}\n"
        f"✅ Wins: {s['wins']}  ❌ Losses: {s['losses']}\n"
        f"🏆 Win rate: {s['win_rate']:.0f}%\n\n"
        f"Want every call in real time with full targets? → /vip"
    )
    await context.bot.send_message(
        cfg.free_channel, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    store: Store = context.application.bot_data["store"]
    user = update.effective_user
    # Referral deep link: t.me/bot?start=<referrer_id>
    if context.args:
        try:
            referrer = int(context.args[0])
            store.record_referral(referrer, user.id)
        except ValueError:
            pass
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    await update.message.reply_text(
        "👋 Welcome. Free signals post automatically in the channel.\n\n"
        "• /vip — unlock full targets, sizing & early posting\n"
        "• /status — your VIP status\n"
        f"• Invite friends, get free VIP:\n{ref_link}",
        disable_web_page_preview=True,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import time

    store: Store = context.application.bot_data["store"]
    uid = update.effective_user.id
    exp = store.vip_expiry(uid)
    refs = store.referral_count(uid)
    if exp and exp > time.time():
        days = int((exp - time.time()) / 86400)
        txt = f"✅ VIP active — {days} day(s) left."
    else:
        txt = "❌ No active VIP. Use /vip to subscribe."
    await update.message.reply_text(f"{txt}\n👥 Referrals: {refs}")


async def cmd_vip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.application.bot_data["cfg"]
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"⭐ Subscribe — {cfg.vip_price_stars} Stars / {cfg.vip_days}d",
                               callback_data="buy_vip")]]
    )
    await update.message.reply_text(
        "<b>VIP membership</b>\n"
        "• Every signal in real time (not just teasers)\n"
        "• Full TP2/TP3 + position sizing\n"
        "• Private VIP channel access\n"
        "• Early posting before the free channel",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


async def on_buy_vip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.application.bot_data["cfg"]
    await update.callback_query.answer()
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title="VIP Signals",
        description=f"{cfg.vip_days} days of VIP access",
        payload="vip_sub",
        currency="XTR",  # Telegram Stars
        prices=[LabeledPrice("VIP", cfg.vip_price_stars)],
    )


async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.pre_checkout_query.answer(ok=True)


async def on_paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.application.bot_data["cfg"]
    store: Store = context.application.bot_data["store"]
    uid = update.effective_user.id
    store.grant_vip(uid, cfg.vip_days)

    # Auto-grant VIP channel access via single-use invite link.
    invite = None
    if cfg.vip_channel:
        try:
            link = await context.bot.create_chat_invite_link(
                cfg.vip_channel, member_limit=1
            )
            invite = link.invite_link
        except Exception as e:  # noqa: BLE001 - surface but don't crash payment
            log.warning("invite link failed: %s", e)

    msg = f"🎉 VIP activated for {cfg.vip_days} days!"
    if invite:
        msg += f"\nJoin the VIP channel: {invite}"
    await update.message.reply_text(msg, disable_web_page_preview=True)


async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin: trigger a scan immediately."""
    cfg: Config = context.application.bot_data["cfg"]
    if update.effective_user.id not in cfg.admin_ids:
        return
    await update.message.reply_text("Scanning…")
    await scan_and_post(context)
    await update.message.reply_text("Done.")


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------
def build_app(cfg: Config | None = None) -> Application:
    cfg = cfg or Config()
    app = Application.builder().token(cfg.bot_token).build()
    app.bot_data.update(
        cfg=cfg, store=Store(cfg.db_path), src=build_data_source(cfg)
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("vip", cmd_vip))
    app.add_handler(CommandHandler("post", cmd_post))
    app.add_handler(CallbackQueryHandler(on_buy_vip, pattern="^buy_vip$"))
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_paid))

    jq = app.job_queue
    jq.run_repeating(scan_and_post, interval=cfg.post_interval_min * 60, first=10)
    jq.run_repeating(post_weekly_stats, interval=7 * 86400, first=7 * 86400)
    return app


def main() -> None:
    app = build_app()
    log.info("starting bot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

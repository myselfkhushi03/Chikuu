"""
✨ Webify Bot — Entry Point
Sab modules yahan wire hote hain.
"""
import asyncio
import traceback

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import (
    BOT_TOKEN, PORT, WEBHOOK_URL, WEBHOOK_PATH, WEBHOOK_FULL, WEBHOOK_SECRET,
)
from database import db
from logger import log
from utils import escape_html

# Handlers
from handlers.start import start, help_cmd, status_cmd, stats_cmd, reset_cmd, cancel_cmd
from handlers.code_mode import handle_code_text
from handlers.files_mode import on_document, done_cmd
from handlers.details_mode import handle_details_text
from handlers.callbacks import on_callback


# ============================================================
# TEXT ROUTER — mode ke hisaab se sahi handler ko bhejta hai
# ============================================================
async def text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        s = await db.get_session(uid)
        mode = s.get("mode")
    except Exception:
        log.exception("text_router: session fetch fail")
        mode = None

    if mode == "code":
        await handle_code_text(update, ctx)
    elif mode == "details":
        await handle_details_text(update, ctx)
    else:
        await update.message.reply_text(
            "Bhai pehle /start kar ke mode choose kar 👇"
        )


# ============================================================
# ERROR HANDLER — har error visible
# ============================================================
async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Exception while handling update:", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            tb = "".join(traceback.format_exception(None, ctx.error, ctx.error.__traceback__))
            await update.effective_message.reply_text(
                f"⚠️ <b>Bot error:</b>\n<code>{escape_html(str(ctx.error))}</code>\n\n"
                f"<i>{escape_html(tb[-400:])}</i>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("Failed to notify user of error")


# ============================================================
# LIFECYCLE
# ============================================================
async def on_startup(app: Application):
    # Mongo
    await db.connect()

    # Webhook
    webhook_url = WEBHOOK_FULL
    await app.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )
    log.info(f"✅ Webhook set: {webhook_url}")


async def on_shutdown(app: Application):
    try:
        await app.bot.delete_webhook(drop_pending_updates=False)
        log.info("🔌 Webhook deleted")
    except Exception:
        log.exception("delete_webhook fail")
    await db.close()


# ============================================================
# MAIN
# ============================================================
def main():
    log.info("🚀 Webify Bot starting...")
    log.info(f"   PORT          = {PORT}")
    log.info(f"   WEBHOOK_URL   = {WEBHOOK_URL}")
    log.info(f"   WEBHOOK_PATH  = {WEBHOOK_PATH}")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    # ---------- Commands ----------
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("help",   help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("stats",  stats_cmd))
    app.add_handler(CommandHandler("reset",  reset_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("done",   done_cmd))

    # ---------- Callbacks ----------
    app.add_handler(CallbackQueryHandler(on_callback))

    # ---------- Documents (files mode) ----------
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))

    # ---------- Text (routed) ----------
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # ---------- Errors ----------
    app.add_error_handler(error_handler)

    # ---------- Run ----------
    log.info(f"🌐 Starting webhook server on 0.0.0.0:{PORT}{WEBHOOK_PATH}")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH.lstrip("/"),
        secret_token=WEBHOOK_SECRET,
        webhook_url=WEBHOOK_FULL,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()

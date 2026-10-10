"""💻 Code mode — HTML paste → website."""
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import db
from keyboards import after_generate_kb
from utils import escape_html, file_count
from logger import log


async def start_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    try:
        s = await db.get_session(uid)
        s["mode"] = "code"
        s["files"] = {}
        s["temp"] = {}
        await db.save_session(uid, s)
    except Exception:
        log.exception("start_code fail")

    await q.edit_message_text(
        "💻 <b>Code Mode</b>\n\n"
        "Apna poora HTML code paste kar (CSS/JS inline ho toh best).\n\n"
        "Bhej de 👇",
        parse_mode=ParseMode.HTML,
    )


async def handle_code_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""

    try:
        s = await db.get_session(uid)
        if s.get("mode") != "code":
            return  # let other handler handle

        if "<html" not in text.lower() and "<!doctype" not in text.lower():
            await update.message.reply_text(
                "⚠️ Ye valid HTML nahi lag raha.\n"
                "Phir bhi save kar raha hun — but <code>&lt;html&gt;</code> tag use kar next time.",
                parse_mode=ParseMode.HTML,
            )

        s["files"] = {"index.html": text}
        s["mode"] = None
        await db.save_session(uid, s)
        await db.inc_generations(uid)

        await update.message.reply_text(
            f"✨ <b>Website ready!</b> 🎉\n\n"
            f"📁 Files: <b>{file_count(s)}</b>\n"
            f"  • <code>index.html</code>\n\n"
            f"Download kar 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=after_generate_kb(),
        )
    except Exception as e:
        log.exception("handle_code_text fail")
        await update.message.reply_text(
            f"❌ <b>Code mode error:</b>\n<code>{escape_html(e)}</code>",
            parse_mode=ParseMode.HTML,
  )

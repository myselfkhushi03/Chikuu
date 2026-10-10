"""🚀 /start /help /status /reset /cancel."""
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database import db
from keyboards import main_menu_kb, back_kb
from utils import escape_html, list_files
from logger import log


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        await db.upsert_user(user.id, user.username or "", user.first_name or "")
        await db.reset_session(user.id)
    except Exception:
        log.exception("start: db fail")

    text = (
        f"✨ <b>Webify Bot</b> — GenZ Edition ✨\n\n"
        f"Hey <b>{escape_html(user.first_name)}</b> 👋\n\n"
        f"Main teri website bana dunga — 3 tarike se:\n\n"
        f"💻 <b>Code</b> — seedha HTML/CSS/JS paste kar\n"
        f"📁 <b>Files</b> — files bhej de (zip bhi chalega)\n"
        f"📝 <b>Details</b> — naam, tagline, color bata\n\n"
        f"Kaunsa mode? 👇"
    )

    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
        )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>Webify Bot Help</b>\n\n"
        "<b>Commands:</b>\n"
        "/start  — Main menu\n"
        "/help   — Ye message\n"
        "/status — Session info\n"
        "/stats  — Global stats\n"
        "/done   — Files mode complete\n"
        "/cancel — Cancel flow\n"
        "/reset  — Clear session\n\n"
        "<b>Modes:</b>\n"
        "• <b>Code</b> — HTML/CSS/JS paste kar\n"
        "• <b>Files</b> — ek-ek file ya .zip bhej\n"
        "• <b>Details</b> — guided flow (5 steps)\n\n"
        "Har mode ke baad <b>ZIP + Single HTML</b> milega 💅"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        s = await db.get_session(uid)
        files, extra = list_files(s)
    except Exception as e:
        log.exception("status fail")
        await update.message.reply_text(f"❌ Status error: <code>{escape_html(e)}</code>",
                                        parse_mode=ParseMode.HTML)
        return

    body = (
        f"📊 <b>Session Status</b>\n\n"
        f"👤 User: <code>{uid}</code>\n"
        f"🎯 Mode: <code>{escape_html(s.get('mode') or '—')}</code>\n"
        f"📁 Files: <b>{len(files)}</b>\n"
    )
    if files:
        body += "\n".join(f"  • <code>{escape_html(f)}</code>" for f in files)
        if extra:
            body += f"\n  <i>+{extra} more</i>"
    else:
        body += "  <i>(none)</i>"
    await update.message.reply_text(body, parse_mode=ParseMode.HTML)


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        g = await db.get_global_stats()
    except Exception as e:
        await update.message.reply_text(f"❌ {escape_html(e)}", parse_mode=ParseMode.HTML)
        return
    text = (
        f"🌍 <b>Global Stats</b>\n\n"
        f"👥 Users: <b>{g['total_users']}</b>\n"
        f"🚀 Generations: <b>{g['total_generations']}</b>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await db.reset_session(update.effective_user.id)
    except Exception:
        log.exception("reset fail")
    await update.message.reply_text("🗑️ Session reset. Fresh start! /start")


async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await db.reset_session(update.effective_user.id)
    except Exception:
        log.exception("cancel fail")
    await update.message.reply_text("❌ Cancel. /start se dobara try kar.")

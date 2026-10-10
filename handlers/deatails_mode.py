"""📝 Details mode — guided 5-step flow."""
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from database import db
from keyboards import layout_kb, after_generate_kb
from templates import build_template
from utils import escape_html
from logger import log


async def start_details(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    try:
        s = await db.get_session(uid)
        s["mode"] = "details"
        s["files"] = {}
        s["temp"] = {}
        await db.save_session(uid, s)
    except Exception:
        log.exception("start_details fail")

    await q.edit_message_text(
        "📝 <b>Details Mode</b>\n\n"
        "Step 1/5 — Site ka <b>naam</b> kya rakhu? 👇",
        parse_mode=ParseMode.HTML,
    )


async def handle_details_text(update: Update, ctx:

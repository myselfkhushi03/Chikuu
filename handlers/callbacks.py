"""🔘 Saare callback query handlers — ek jagah."""
import io

from telegram import Update, InputFile
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes

from database import db
from keyboards import back_kb
from utils import (
    build_zip, build_single_html, escape_html, list_files,
)
from logger import log

from handlers.code_mode import start_code
from handlers.files_mode import start_files
from handlers.details_mode import start_details, handle_layout_choice
from handlers.start import start


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    log.info(f"callback uid={uid} data={data}")

    try:
        # ---------- Navigation ----------
        if data == "home":
            await start(update, ctx)
            return

        if data == "reset":
            await db.reset_session(uid)
            await q.edit_message_text("🗑️ Reset done. /start")
            return

        if data == "status":
            s = await db.get_session(uid)
            files, extra = list_files(s)
            body = (
                f"📊 <b>Session Status</b>\n\n"
                f"🎯 Mode: <code>{escape_html(s.get('mode') or '—')}</code>\n"
                f"📁 Files: <b>{len(files)}</b>\n"
            )
            if files:
                body += "\n".join(f"  • <code>{escape_html(f)}</code>" for f in files)
                if extra:
                    body += f"\n  <i>+{extra} more</i>"
            else:
                body += "  <i>(none)</i>"
            await q.edit_message_text(body, parse_mode=ParseMode.HTML, reply_markup=back_kb())
            return

        # ---------- Mode entry ----------
        if data == "mode_code":
            await start_code(update, ctx)
            return
        if data == "mode_files":
            await start_files(update, ctx)
            return
        if data == "mode_details":
            await start_details(update, ctx)
            return

        # ---------- Layout picker (details mode) ----------
        if data.startswith("layout_"):
            await handle_layout_choice(update, ctx)
            return

        # ---------- Downloads ----------
        if data == "dl_zip":
            s = await db.get_session(uid)
            if not s.get("files"):
                await q.answer("❌ Pehle website banao!", show_alert=True)
                return
            await q.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
            buf = build_zip(s)
            await q.message.reply_document(
                document=InputFile(buf, filename="webify-site.zip"),
                caption="✨ Teri website ka ZIP — enjoy! 💅",
            )
            return

        if data == "dl_html":
            s = await db.get_session(uid)
            html = build_single_html(s)
            if not html:
                await q.answer("❌ index.html nahi mila!", show_alert=True)
                return
            await q.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
            buf = io.BytesIO(html.encode("utf-8"))
            await q.message.reply_document(
                document=InputFile(buf, filename="index.html"),
                caption="✨ Single HTML — direct browser me khol!",
            )
            return

        # ---------- Unknown ----------
        await q.answer("⚠️ Unknown action", show_alert=False)

    except Exception as e:
        log.exception("callback fail")
        try:
            await q.message.reply_text(
                f"❌ <b>Callback error:</b>\n<code>{escape_html(e)}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

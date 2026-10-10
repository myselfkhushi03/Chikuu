"""📁 Files mode — files bhej, /done se generate."""
import io
import zipfile

from telegram import Update
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes

from config import MAX_FILE_SIZE, MAX_FILES_PER_USER
from database import db
from keyboards import after_generate_kb
from utils import escape_html, file_count, is_text_filename
from logger import log


async def start_files(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    try:
        s = await db.get_session(uid)
        s["mode"] = "files"
        s["files"] = {}
        s["temp"] = {}
        await db.save_session(uid, s)
    except Exception:
        log.exception("start_files fail")

    await q.edit_message_text(
        "📁 <b>Files Mode</b>\n\n"
        "Files bhej — ek-ek karke, ya <b>.zip</b> bhi chalega.\n\n"
        "<b>Tip:</b> <code>index.html</code> zaroor ho.\n\n"
        "Jab sab ho jaye toh <code>/done</code> bhej 👇",
        parse_mode=ParseMode.HTML,
    )


async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    doc = update.message.document

    try:
        s = await db.get_session(uid)
        if s.get("mode") != "files":
            await update.message.reply_text(
                "⚠️ Pehle /start → 📁 Files mode select kar.",
            )
            return

        if doc.file_size and doc.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(
                f"❌ File bada hai ({doc.file_size // 1024 // 1024} MB). "
                f"Max {MAX_FILE_SIZE // 1024 // 1024} MB.",
            )
            return

        if file_count(s) >= MAX_FILES_PER_USER:
            await update.message.reply_text(
                f"❌ Max {MAX_FILES_PER_USER} files. /done bhej ya /reset."
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)
        tg_file = await doc.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        name = doc.file_name or "file.bin"

        # ---- ZIP ----
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    added = 0
                    for info in z.infolist():
                        if info.is_dir():
                            continue
                        if "__MACOSX" in info.filename or info.filename.startswith("."):
                            continue
                        fname = info.filename.split("/")[-1] or info.filename
                        if not fname:
                            continue
                        content = z.read(info)
                        try:
                            s["files"][fname] = content.decode("utf-8")
                        except UnicodeDecodeError:
                            s["files"][fname] = content
                            s["files"]["__bin__" + fname] = True
                        added += 1
                await db.save_session(uid, s)
                await update.message.reply_text(
                    f"✅ ZIP extract — <b>{added}</b> files added.\n"
                    f"Total: <b>{file_count(s)}</b> files.\n\n"
                    f"<code>/done</code> bhej jab ready ho.",
                    parse_mode=ParseMode.HTML,
                )
            except zipfile.BadZipFile:
                await update.message.reply_text("❌ ZIP corrupt hai bhai.")
            return

        # ---- Normal file ----
        if is_text_filename(name):
            try:
                s["files"][name] = raw.decode("utf-8")
            except UnicodeDecodeError:
                s["files"][name] = raw
                s["files"]["__bin__" + name] = True
        else:
            s["files"][name] = raw
            s["files"]["__bin__" + name] = True

        await db.save_session(uid, s)
        await update.message.reply_text(
            f"✅ <code>{escape_html(name)}</code> added.\n"
            f"Total: <b>{file_count(s)}</b> files.\n\n"
            f"<code>/done</code> bhej jab ready ho.",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        log.exception("on_document fail")
        await update.message.reply_text(
            f"❌ <b>File error:</b>\n<code>{escape_html(e)}</code>",
            parse_mode=ParseMode.HTML,
        )


async def done_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        s = await db.get_session(uid)
        if s.get("mode") != "files":
            await update.message.reply_text("⚠️ Files mode me nahi ho. /start kar.")
            return
        if not s.get("files"):
            await update.message.reply_text("❌ Koi file nahi mila. Pehle files bhej.")
            return

        s["mode"] = None
        await db.save_session(uid, s)
        await db.inc_generations(uid)

        files = [k for k in s["files"] if not k.startswith("__bin__")]
        listing = "\n".join(f"  • <code>{escape_html(f)}</code>" for f in files[:15])
        extra = f"\n  <i>+{len(files)-15} more</i>" if len(files) > 15 else ""

        await update.message.reply_text(
            f"✨ <b>Website ready!</b> 🎉\n\n"
            f"📁 Files: <b>{len(files)}</b>\n{listing}{extra}\n\n"
            f"Download kar 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=after_generate_kb(),
        )
    except Exception as e:
        log.exception("done_cmd fail")
        await update.message.reply_text(
            f"❌ <b>Done error:</b>\n<code>{escape_html(e)}</code>",
            parse_mode=ParseMode.HTML,
      )

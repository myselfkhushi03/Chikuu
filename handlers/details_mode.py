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


async def handle_details_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    try:
        s = await db.get_session(uid)
        if s.get("mode") != "details":
            return

        t = s.get("temp") or {}

        # ---- Step 1: Title ----
        if "title" not in t:
            t["title"] = text or "Meri Site"
            s["temp"] = t
            await db.save_session(uid, s)
            await update.message.reply_text(
                "📝 Step 2/5 — <b>Tagline</b> kya likhu?\n"
                "(ex: <i>GenZ vibes only ✨</i>)",
                parse_mode=ParseMode.HTML,
            )
            return

        # ---- Step 2: Tagline ----
        if "tagline" not in t:
            t["tagline"] = text or "GenZ vibes only ✨"
            s["temp"] = t
            await db.save_session(uid, s)
            await update.message.reply_text(
                "📝 Step 3/5 — <b>Theme color</b> kaunsa?\n"
                "Hex code bhej jaise <code>#b794f6</code>\n"
                "(ya <code>skip</code>)",
                parse_mode=ParseMode.HTML,
            )
            return

        # ---- Step 3: Color ----
        if "color" not in t:
            c = text.lower()
            if not c or c == "skip":
                c = "#b794f6"
            else:
                c = text
                if not c.startswith("#") or len(c) not in (4, 7):
                    await update.message.reply_text(
                        "⚠️ Hex format chahiye — jaise <code>#b794f6</code> ya <code>skip</code>",
                        parse_mode=ParseMode.HTML,
                    )
                    return
            t["color"] = c
            s["temp"] = t
            await db.save_session(uid, s)
            await update.message.reply_text(
                "📝 Step 4/5 — <b>Layout</b> choose kar 👇",
                parse_mode=ParseMode.HTML,
                reply_markup=layout_kb(),
            )
            return

        # ---- Step 4: Layout (via callback) ----
        if "layout" not in t:
            await update.message.reply_text(
                "👆 Pehle layout button dabaa (upar wale message me).",
            )
            return

        # ---- Step 5: Notes → Build ----
        if "notes" not in t:
            t["notes"] = "" if text.lower() == "skip" else text
            html = build_template(
                t["title"], t["tagline"], t["color"], t["layout"], t["notes"]
            )
            s["files"] = {"index.html": html}
            s["mode"] = None
            await db.save_session(uid, s)
            await db.inc_generations(uid)

            await update.message.reply_text(
                f"✨ <b>Website ready!</b> 🎉\n\n"
                f"🎨 Title: <b>{escape_html(t['title'])}</b>\n"
                f"🎯 Layout: <code>{escape_html(t['layout'])}</code>\n"
                f"🌈 Color: <code>{escape_html(t['color'])}</code>\n\n"
                f"Download kar 👇",
                parse_mode=ParseMode.HTML,
                reply_markup=after_generate_kb(),
            )
            return

    except Exception as e:
        log.exception("handle_details_text fail")
        await update.message.reply_text(
            f"❌ <b>Details mode error:</b>\n<code>{escape_html(e)}</code>",
            parse_mode=ParseMode.HTML,
        )


async def handle_layout_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Layout button click hone pe."""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    layout = q.data.replace("layout_", "")

    try:
        s = await db.get_session(uid)
        if s.get("mode") != "details":
            await q.edit_message_text("⚠️ Session expire ho gaya. /start se dobara.")
            return

        t = s.get("temp") or {}
        t["layout"] = layout
        s["temp"] = t
        await db.save_session(uid, s)

        await q.edit_message_text(
            f"✅ Layout: <b>{escape_html(layout)}</b>\n\n"
            f"📝 Step 5/5 — Koi <b>extra notes / content</b>?\n\n"
            f"(Ya <code>skip</code> likh de)\n👇",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        log.exception("handle_layout_choice fail")
        await q.edit_message_text(
            f"❌ <code>{escape_html(e)}</code>",
            parse_mode=ParseMode.HTML,
        )

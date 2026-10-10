"""
Web Maker Bot — single file (bot.py)
Telegram bot that turns code / files / ZIPs into live websites. Render Web Service + webhook + MongoDB.
Start command:  python bot.py
"""
from config import *
from database import db, init_db
from texts import WELCOME, HELP_TEXT, DIV
from keyboards import *
import asyncio
import html as _html
import io
import logging
import mimetypes
import os
import re
import secrets
import time
import traceback
import zipfile
from urllib.parse import urlparse

import aiohttp
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError,
                                TelegramRetryAfter)
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BotCommand, BotCommandScopeChat, CallbackQuery, ErrorEvent, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from bson.binary import Binary
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError

log = logging.getLogger("webmaker")


# ═════════════════════════ CONFIG (with clear error messages) ═════════════════════════
def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _num(name: str, default, cast=int):
    raw = _env(name, str(default))
    try:
        return cast(raw)
    except ValueError:
        raise SystemExit(f"❌ Environment variable {name} must be a number, but it is: {raw!r}")


BOT_TOKEN = _env("BOT_TOKEN")
WEBHOOK_URL = _env("WEBHOOK_URL")
WEBHOOK_SECRET = _env("WEBHOOK_SECRET")
MONGO_URL = _env("MONGO_URL")

_missing = [n for n, v in (("BOT_TOKEN", BOT_TOKEN), ("WEBHOOK_URL", WEBHOOK_URL),
                           ("WEBHOOK_SECRET", WEBHOOK_SECRET), ("MONGO_URL", MONGO_URL)) if not v]
if _missing:
    raise SystemExit("❌ Missing environment variables on Render: " + ", ".join(_missing))

if not WEBHOOK_URL.startswith(("http://", "https://")):
    WEBHOOK_URL = "https://" + WEBHOOK_URL
WEBHOOK_URL = WEBHOOK_URL.rstrip("/")
if not WEBHOOK_URL.startswith("https://"):
    raise SystemExit("❌ WEBHOOK_URL must start with https:// (Telegram requires HTTPS). "
                     "Example: https://your-app.onrender.com")
if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", WEBHOOK_SECRET):
    raise SystemExit("❌ WEBHOOK_SECRET may contain only letters, digits, underscore and hyphen (max 256 chars).")

PORT = _num("PORT", 1000)
ADMINS = {int(x) for x in re.findall(r"-?\d+", _env("ADMIN_ID"))}
DB_NAME = _env("DB_NAME", "webmaker")
MAX_SITES = _num("MAX_SITES", 15)
MAX_FILE = int(_num("MAX_FILE_MB", 15, float) * 1024 * 1024)
MAX_SITE = int(_num("MAX_SITE_MB", 60, float) * 1024 * 1024)
RENDER_API_KEY = _env("RENDER_API_KEY")
RENDER_SERVICE_ID = _env("RENDER_SERVICE_ID")

BASE_HOST = urlparse(WEBHOOK_URL).hostname or "localhost"
LOCAL_HOSTS = {BASE_HOST, "localhost", "127.0.0.1"}
RESERVED_SLUGS = {"admin", "api", "s", "health", "webhook", "static", "www"}
BOT_USERNAME = ""  # filled at startup

for _ext, _mt in {".webp": "image/webp", ".woff2": "font/woff2", ".woff": "font/woff",
                  ".mjs": "application/javascript", ".svg": "image/svg+xml", ".ico": "image/x-icon",
                  ".json": "application/json", ".webmanifest": "application/manifest+json",
                  ".avif": "image/avif"}.items():
    mimetypes.add_type(_mt, _ext)


def now() -> int:
    return int(time.time())


def esc(s) -> str:
    return _html.escape(str(s))


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1048576:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1048576:.1f} MB"


# ═════════════════════════ DATABASE ═════════════════════════
class _DB:
    users = sites = files = None


db = _DB()


async def init_db():
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    try:
        await client.admin.command("ping")
    except Exception as e:
        raise SystemExit("❌ Cannot connect to MongoDB. Check MONGO_URL, the database user/password and that "
                         f"Atlas 'Network Access' allows 0.0.0.0/0.\nDetails: {type(e).__name__}: {e}")
    d = client[DB_NAME]
    db.users, db.sites, db.files = d["users"], d["sites"], d["files"]
    await db.users.create_index("uid", unique=True)
    await db.sites.create_index("sid", unique=True)
    await db.sites.create_index("slug", unique=True)
    await db.sites.create_index("code", unique=True)
    await db.sites.create_index("owner")
    await db.sites.create_index("domain", unique=True, partialFilterExpression={"domain": {"$type": "string"}})
    await db.files.create_index([("sid", 1), ("path", 1)], unique=True)
    log.info("MongoDB connected")


# ═════════════════════════ FILE / SITE HELPERS ═════════════════════════
def clean_path(p: str):
    """Safe relative path. '' = root. None = invalid."""
    p = (p or "").replace("\\", "/")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if any(x == ".." for x in parts):
        return None
    out = "/".join(parts)
    return out if len(out) <= 200 else None


def strip_fence(t: str) -> str:
    t = t.strip()
    m = re.match(r"^```[\w+-]*\n(.*?)\n?```$", t, re.S)
    return m.group(1) if m else t


def parse_blocks(text: str) -> dict:
    """Plain code -> index.html. Several files -> '### filename' separators."""
    text = text.strip()
    parts = re.split(r"(?m)^###\s*([^\s]+)\s*$", text)
    if len(parts) == 1:
        return {"index.html": strip_fence(text)}
    out = {}
    for i in range(1, len(parts), 2):
        out[parts[i]] = strip_fence(parts[i + 1])
    return out


def looks_like_code(t: str) -> bool:
    s = (t or "").strip()
    if not s or s.startswith("/"):
        return False
    if re.search(r"(?m)^###\s*\S+\s*$", s) or s.startswith("```"):
        return True
    return bool(re.search(r"<\s*(!doctype|html|head|body|div|section|main|header|footer|nav|style|script|"
                          r"h[1-6]|p|span|a|img|form|button|ul|ol|table|svg|canvas|link|meta)\b", s, re.I))


async def site_size(sid: str) -> int:
    r = await db.files.aggregate([{"$match": {"sid": sid}}, {"$group": {"_id": None, "s": {"$sum": "$size"}}}]).to_list(1)
    return r[0]["s"] if r else 0


async def put(sid: str, path: str, data: bytes, check: bool = True):
    p = clean_path(path)
    if not p:
        raise ValueError(f"'{path}' is not a valid file name. Avoid '..' and very long names.")
    if len(data) > MAX_FILE:
        raise ValueError(f"'{path}' is {fmt_size(len(data))}. The limit is {fmt_size(MAX_FILE)} per file.")
    if check:
        if not await db.sites.find_one({"sid": sid}, {"_id": 1}):
            raise ValueError("This website no longer exists.")
        old = await db.files.find_one({"sid": sid, "path": p}, {"size": 1})
        total = await site_size(sid) - (old["size"] if old else 0)
        if total + len(data) > MAX_SITE:
            raise ValueError(f"Site size limit reached ({fmt_size(MAX_SITE)} per website).")
    mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
    await db.files.update_one({"sid": sid, "path": p},
                              {"$set": {"data": Binary(data), "mime": mime, "size": len(data), "ts": now()}},
                              upsert=True)
    await db.sites.update_one({"sid": sid}, {"$set": {"updated": now()}})


async def add_zip(sid: str, data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()
                 and not i.filename.startswith("__MACOSX")
                 and not any(seg.startswith(".") for seg in i.filename.split("/"))]
        if not infos:
            raise ValueError("The ZIP does not contain any usable files.")
        if len(infos) > 500:
            raise ValueError("The ZIP has too many files (max 500).")
        if not await db.sites.find_one({"sid": sid}, {"_id": 1}):
            raise ValueError("This website no longer exists.")
        if sum(i.file_size for i in infos) + await site_size(sid) > MAX_SITE:
            raise ValueError(f"Site size limit reached ({fmt_size(MAX_SITE)} per website).")
        names = [i.filename for i in infos]
        prefix = ""
        firsts = {n.split("/")[0] for n in names}
        if len(firsts) == 1 and all("/" in n for n in names):
            prefix = firsts.pop() + "/"
        count = skipped = 0
        for i in infos:
            name = i.filename[len(prefix):] if prefix else i.filename
            try:
                await put(sid, name, z.read(i), check=False)
                count += 1
            except ValueError:
                skipped += 1
    if count == 0:
        raise ValueError("None of the files in the ZIP could be saved (names too long or files too big).")
    return count, skipped


async def new_site(owner: int) -> dict:
    sid = secrets.token_hex(6)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        slug = "".join(secrets.choice(alphabet) for _ in range(6))
        if slug not in RESERVED_SLUGS and not await db.sites.find_one({"slug": slug}, {"_id": 1}):
            break
    doc = {"sid": sid, "slug": slug, "code": "EC-" + secrets.token_hex(5).upper(), "owner": owner,
           "title": "Untitled Site", "created": now(), "updated": now(), "views": 0}
    await db.sites.insert_one(doc)
    return doc


async def drop_site_data(sid: str):
    await db.files.delete_many({"sid": sid})
    await db.sites.delete_one({"sid": sid})


async def refresh_title(sid: str):
    f = await db.files.find_one({"sid": sid, "path": "index.html"}) or \
        await db.files.find_one({"sid": sid, "path": {"$regex": r"\.html?$"}})
    if f:
        m = re.search(rb"<title[^>]*>(.*?)</title>", bytes(f["data"][:20000]), re.I | re.S)
        if m:
            t = m.group(1).decode("utf8", "ignore").strip()[:60]
            if t:
                await db.sites.update_one({"sid": sid}, {"$set": {"title": t}})


async def delete_site(site: dict):
    await drop_site_data(site["sid"])
    if site.get("domain"):
        await render_domain(False, site["domain"])


def site_url(site: dict) -> str:
    return f"https://{site['domain']}/" if site.get("domain") else f"{WEBHOOK_URL}/s/{site['slug']}/"


async def can_edit(uid: int, site: dict) -> bool:
    if uid in ADMINS or site.get("owner") == uid:
        return True
    u = await db.users.find_one({"uid": uid}, {"unlocked": 1})
    return bool(u and site["sid"] in u.get("unlocked", []))


async def quota_ok(uid: int) -> bool:
    return uid in ADMINS or await db.sites.count_documents({"owner": uid}) < MAX_SITES


async def render_domain(add: bool, domain: str):
    """Optional: add/remove custom domain on Render through its API. Returns HTTP status or None."""
    if not (RENDER_API_KEY and RENDER_SERVICE_ID):
        return None
    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/custom-domains"
    headers = {"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            if add:
                async with s.post(url, json={"name": domain}, headers=headers) as r:
                    return r.status
            async with s.delete(f"{url}/{domain}", headers=headers) as r:
                return r.status
    except Exception as e:  # noqa
        log.warning("Render API error: %s", e)
        return None


async def read_doc(bot, obj) -> bytes:
    size = getattr(obj, "file_size", None)
    if size and size > MAX_FILE:
        raise ValueError(f"That file is {fmt_size(size)}. The limit is {fmt_size(MAX_FILE)} per file.")
    buf = io.BytesIO()
    await bot.download(obj, destination=buf)
    return buf.getvalue()


# ═════════════════════════ ERROR EXPLAINER ═════════════════════════
def oops(title: str, why: str, fix: str = "") -> str:
    """Friendly error message. `why` and `fix` must already be HTML-safe."""
    t = f"⚠️ <b>{esc(title)}</b>\n{DIV}\n❌ <b>What went wrong</b>\n{why}"
    if fix:
        t += f"\n\n💡 <b>How to fix</b>\n{fix}"
    return t


def explain(e: BaseException):
    """-> (title, what_went_wrong, how_to_fix, notify_admin)"""
    if isinstance(e, zipfile.BadZipFile):
        return ("Broken ZIP file", "The ZIP is corrupted or is not a real ZIP archive.",
                "Create the ZIP again and upload it as a <b>File</b>.", False)
    if isinstance(e, ValueError):
        return ("Invalid input", esc(e), "Fix it and try again.", False)
    if isinstance(e, PyMongoError):
        return ("Database unavailable", "The database did not respond in time.",
                "Wait a few seconds and try again. If it keeps happening, contact the admin.", True)
    if isinstance(e, TelegramRetryAfter):
        return ("Too many requests", f"Telegram asked us to slow down for {e.retry_after} seconds.",
                "Please try again shortly.", False)
    if isinstance(e, TelegramBadRequest):
        return ("Telegram rejected the action", esc(getattr(e, "message", e))[:200],
                "Try again, or press /start to reset.", True)
    if isinstance(e, (TelegramNetworkError, asyncio.TimeoutError, aiohttp.ClientError)):
        return ("Network problem", "The connection timed out while talking to Telegram.", "Please try again.", True)
    return ("Unexpected error", f"<code>{esc(type(e).__name__)}: {esc(e)[:160]}</code>",
            "Press /cancel and try again. The admin has been notified automatically.", True)


# ═════════════════════════ TEXTS & KEYBOARDS ═════════════════════════
DIV = "━━━━━━━━━━━━━━━━"

BTN_CREATE = "➕ Create Website"
BTN_MY = "📂 My Websites"
BTN_EDIT = "✏️ Edit by Code"
BTN_HELP = "❓ Help"
BTN_ADMIN = "🛠 Admin Panel"

WELCOME = (f"<b>✦ WEB MAKER ✦</b>\n<i>Turn code into live websites, right inside Telegram.</i>\n\n{DIV}\n"
           "⚡ Paste HTML / CSS / JS code\n📄 Send a file or a ZIP\n🔗 Get an instant short link\n"
           "✏️ Edit anytime with a private code\n🌍 Connect your own domain\n"
           f"{DIV}\n\n<i>Tip: just send me your code or files — no buttons needed.</i>")

QUICK_TEXT = "<b>⚡ Quick Actions</b>\nPick an option, or use the keyboard at the bottom."

MODE_TEXT = (f"<b>➕ Create a Website</b>\n{DIV}\nChoose how you want to build it:\n\n"
             "📝 <b>Paste Code</b> — send HTML as a message\n📄 <b>Single File</b> — one file or one ZIP\n"
             "📦 <b>Multiple Files</b> — many files, folders or a ZIP\n\n"
             "<i>Or skip this and simply send your code or files.</i>")

HELP_TEXT = (f"<b>❓ How it works</b>\n{DIV}\n"
             "<b>1 · Create</b>\n"
             "Send HTML code or any file directly — or tap <i>Create Website</i>.\n"
             "• <b>Several files in one message?</b> Separate them:\n"
             "<code>### index.html\n&lt;h1&gt;Hello&lt;/h1&gt;\n### style.css\nbody{background:#111}</code>\n"
             "• <b>Many files / folders?</b> Send a <b>.zip</b>, or select several files and send them as <i>File</i>.\n"
             "• <b>Long code?</b> Telegram limits messages to 4096 chars — upload a .html file instead.\n\n"
             "<b>2 · Edit</b>\nEvery site has a private <b>edit code</b> like <code>EC-1A2B3C4D5E</code>. "
             "Use <i>Edit by Code</i> or <code>/edit CODE</code> from any account.\n\n"
             "<b>3 · Share</b>\nGet a short link <code>/s/yourname/</code>. Rename it or connect your own domain.\n\n"
             f"<b>Commands</b>\n/new · /mysites · /edit CODE · /cancel · /help\n\n"
             f"<i>Limits: {MAX_SITES} sites per user · {fmt_size(MAX_FILE)} per file · {fmt_size(MAX_SITE)} per site.</i>")

NOT_CODE_TEXT = (f"🤔 <b>That doesn't look like website code</b>\n{DIV}\n"
                 "I build sites from <b>HTML/CSS/JS</b> code or <b>files</b>.\n\n"
                 "• Paste your HTML here\n• Or send a file / ZIP\n• Or use the buttons below.")


def B(text, data=None, url=None):
    if url:
        return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=data)


def KB(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def reply_kb(uid: int):
    rows = [[KeyboardButton(text=BTN_CREATE), KeyboardButton(text=BTN_MY)],
            [KeyboardButton(text=BTN_EDIT), KeyboardButton(text=BTN_HELP)]]
    if uid in ADMINS:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True,
                               input_field_placeholder="Send code or files to build a website…")


def menu_kb(uid: int):
    rows = [[B("➕ Create Website", "new")],
            [B("📂 My Websites", "my"), B("✏️ Edit by Code", "editcode")],
            [B("❓ Help", "help")]]
    if uid in ADMINS:
        rows.append([B("🛠 Admin Panel", "adm")])
    return KB(*rows)


def mode_kb():
    return KB([B("📝 Paste Code", "m:paste")],
              [B("📄 Single File / ZIP", "m:single")],
              [B("📦 Multiple Files", "m:multi")],
              [B("⬅️ Menu", "menu")])


cancel_kb = KB([B("✖️ Cancel", "cancel")])


def done_kb(sid: str):
    return KB([B("✅ Done", f"done:{sid}"), B("✖️ Cancel", "cancel")])


async def card(site: dict) -> str:
    n = await db.files.count_documents({"sid": site["sid"]})
    size = await site_size(site["sid"])
    dom = f"\n🌍 <b>Domain</b>  <code>{esc(site['domain'])}</code>" if site.get("domain") else ""
    return (f"🌐 <b>{esc(site['title'])}</b>\n{DIV}\n"
            f"🔗 <b>Link</b>\n{esc(site_url(site))}\n\n"
            f"🔑 <b>Edit code</b>  <code>{site['code']}</code>{dom}\n\n"
            f"📁 {n} files  ·  💾 {fmt_size(size)}  ·  👁 {site.get('views', 0)} views\n{DIV}\n"
            "<i>Keep the edit code private — anyone with it can edit this site.</i>")


def panel_kb(site: dict):
    sid = site["sid"]
    rows = []
    if site_url(site).startswith("https://"):
        rows.append([B("🌍 Open Website", url=site_url(site))])
    rows += [[B("📝 Paste Code", f"pe:{sid}"), B("📤 Upload Files", f"up:{sid}")],
             [B("📁 Files", f"fl:{sid}"), B("🔗 Short Link", f"sl:{sid}")],
             [B("🌐 Custom Domain", f"dm:{sid}"), B("🔑 Edit Code", f"code:{sid}")],
             [B("🗑 Delete", f"del:{sid}"), B("⬅️ My Sites", "my")]]
    return KB(*rows)


# ═════════════════════════ WEBSITE SERVER ═════════════════════════
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:system-ui,Segoe UI,Roboto,sans-serif;
background:radial-gradient(1200px 600px at 50%% -10%%,#3b4cca33,transparent),#0b0d17;color:#e8eaf6;text-align:center;padding:24px}
.c{max-width:520px}h1{font-size:3.4rem;margin:.1em 0;background:linear-gradient(135deg,#5b6cff,#a46bff);-webkit-background-clip:text;color:transparent}
h2{margin:.2em 0}p{color:#9aa3c7;line-height:1.6}
a{display:inline-block;margin-top:18px;padding:12px 26px;border-radius:12px;background:linear-gradient(135deg,#5b6cff,#8a5bff);color:#fff;text-decoration:none;font-weight:600}
</style></head><body><div class="c"><h1>%(code)s</h1><h2>%(title)s</h2><p>%(msg)s</p>%(extra)s</div></body></html>"""


def page(status: int, code: str, title: str, msg: str, extra: str = ""):
    return web.Response(text=_PAGE % {"code": code, "title": title, "msg": msg, "extra": extra},
                        status=status, content_type="text/html")


def not_found():
    return page(404, "404", "Page not found", "The page you are looking for doesn't exist or was removed.")


async def serve_site(site: dict, tail: str, is_dir: bool):
    sid = site["sid"]
    p = clean_path(tail)
    if p is None:
        return not_found()
    if not p:
        cands = ["index.html", "index.htm"]
    elif is_dir:
        cands = [p + "/index.html"]
    else:
        cands = [p, p + ".html", p + "/index.html"]
    f = None
    for c in cands:
        f = await db.files.find_one({"sid": sid, "path": c})
        if f:
            break
    if not f and not p:
        f = await db.files.find_one({"sid": sid, "path": {"$regex": r"\.html?$"}}) or await db.files.find_one({"sid": sid})
    if not f:
        e = await db.files.find_one({"sid": sid, "path": "404.html"})
        if e:
            return web.Response(body=bytes(e["data"]), status=404, content_type="text/html", charset="utf-8")
        return not_found()
    if not p:
        asyncio.create_task(db.sites.update_one({"sid": sid}, {"$inc": {"views": 1}}))
    mime = f.get("mime") or "application/octet-stream"
    textual = mime.startswith("text/") or mime in ("application/javascript", "application/json", "image/svg+xml")
    return web.Response(body=bytes(f["data"]), content_type=mime, charset="utf-8" if textual else None,
                        headers={"Cache-Control": "public, max-age=60", "X-Content-Type-Options": "nosniff"})


def _req_host(request) -> str:
    return request.host.split(":")[0].lower()


async def _site_by_host(host: str):
    s = await db.sites.find_one({"domain": host})
    if not s and host.startswith("www."):
        s = await db.sites.find_one({"domain": host[4:]})
    return s


async def h_health(request):
    return web.json_response({"ok": True})


async def h_site_redirect(request):
    q = f"?{request.query_string}" if request.query_string else ""
    raise web.HTTPFound(f"/s/{request.match_info['slug']}/{q}")


async def h_site(request):
    site = await db.sites.find_one({"slug": request.match_info["slug"].lower()})
    if not site:
        return not_found()
    return await serve_site(site, request.match_info["tail"], request.path.endswith("/"))


async def h_root(request):
    host = _req_host(request)
    tail = request.match_info["tail"]
    if host not in LOCAL_HOSTS:
        site = await _site_by_host(host)
        if site:
            return await serve_site(site, tail, request.path.endswith("/"))
        return page(404, "404", "Domain not connected",
                    "This domain is not connected to any website yet.")
    if tail == "":
        extra = f'<a href="https://t.me/{BOT_USERNAME}">Open Telegram Bot</a>' if BOT_USERNAME else ""
        return page(200, "🌐", "Web Maker",
                    "Create and host websites straight from Telegram — paste code, upload files or a ZIP, and go live instantly.",
                    extra)
    return not_found()


@web.middleware
async def web_error_middleware(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:  # noqa
        ref = secrets.token_hex(3)
        log.exception("web error #%s on %s", ref, request.path)
        if request.path == "/webhook":
            return web.Response(status=200, text="error logged")  # avoid Telegram retry storms
        if isinstance(e, PyMongoError):
            return page(503, "503", "Temporarily unavailable",
                        f"The database is not responding. Please try again in a moment.<br><small>Ref #{ref}</small>")
        return page(500, "500", "Something went wrong",
                    f"An unexpected error occurred on our side.<br><small>Ref #{ref}</small>")


def add_routes(app: web.Application):
    app.router.add_get("/health", h_health)
    app.router.add_get("/s/{slug}", h_site_redirect)
    app.router.add_get("/s/{slug}/{tail:.*}", h_site)
    app.router.add_get("/{tail:.*}", h_root)


r = Router()
admin_only = F.from_user.id.in_(ADMINS)
ALBUMS: dict = {}          # media_group_id -> (site id, timestamp)
ALBUM_LOCK = asyncio.Lock()


class S(StatesGroup):
    paste_new = State()
    single_new = State()
    multi = State()
    edit_code = State()
    paste_edit = State()
    slug = State()
    domain = State()
    broadcast = State()


def plain_text(m: Message) -> bool:
    return bool(m.text) and not m.text.startswith("/")


# ═════════════════════════ middleware: register users + ban check ═════════════════════════
class Guard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u and not u.is_bot:
            try:
                await db.users.update_one(
                    {"uid": u.id},
                    {"$set": {"name": u.full_name, "username": u.username, "last": now()},
                     "$setOnInsert": {"joined": now(), "banned": False, "unlocked": []}}, upsert=True)
                if u.id not in ADMINS:
                    d = await db.users.find_one({"uid": u.id}, {"banned": 1})
                    if d and d.get("banned"):
                        try:
                            await data["bot"].send_message(u.id, "🚫 <b>Access denied</b>\nYou are banned from using this bot.")
                        except Exception:  # noqa
                            pass
                        return
            except PyMongoError:
                log.exception("Guard: database error (continuing without ban check)")
        return await handler(event, data)


# ═════════════════════════ helpers ═════════════════════════
async def show(ev, text, kb=None):
    """Edit the message in place for callbacks, send a new one for messages."""
    if isinstance(ev, CallbackQuery):
        try:
            await ev.answer()
        except Exception:  # noqa
            pass
        msg = ev.message
        if not isinstance(msg, Message):
            return await ev.bot.send_message(ev.from_user.id, text, reply_markup=kb)
        try:
            await msg.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                return
            await msg.answer(text, reply_markup=kb)
    else:
        await ev.answer(text, reply_markup=kb)


async def reset(state: FSMContext):
    """Clear state; remove a freshly created empty site if the user abandons it."""
    d = await state.get_data()
    if d.get("fresh") and d.get("sid") and not await db.files.count_documents({"sid": d["sid"]}):
        await db.sites.delete_one({"sid": d["sid"]})
    await state.clear()


async def send_card(ev, site, banner=""):
    await show(ev, banner + await card(site), panel_kb(site))


async def finish_new(ev, site):
    await refresh_title(site["sid"])
    site = await db.sites.find_one({"sid": site["sid"]})
    await send_card(ev, site, banner="✨ <b>Your website is live!</b>\n\n")
    if site["owner"] not in ADMINS and ADMINS:
        try:
            who = ev.from_user
            await ev.bot.send_message(min(ADMINS), f"🆕 <b>New site</b> by <a href='tg://user?id={who.id}'>{esc(who.full_name)}</a> "
                                                  f"(<code>{who.id}</code>)\n{esc(site_url(site))}")
        except Exception:  # noqa
            pass


async def auth(c: CallbackQuery, sid: str):
    site = await db.sites.find_one({"sid": sid})
    if not site:
        await c.answer("This website no longer exists.", show_alert=True)
        return None
    if not await can_edit(c.from_user.id, site):
        await c.answer("You don't have access to this website.", show_alert=True)
        return None
    return site


def limit_msg():
    return oops("Website limit reached", f"You already have <b>{MAX_SITES}</b> websites.",
                "Delete one from <b>My Websites</b>, then try again.")


# ═════════════════════════ commands & bottom keyboard ═════════════════════════
@r.message(CommandStart())
@r.message(Command("menu"))
async def cmd_start(m: Message, state: FSMContext):
    await reset(state)
    await m.answer(WELCOME, reply_markup=reply_kb(m.from_user.id))
    await m.answer(QUICK_TEXT, reply_markup=menu_kb(m.from_user.id))


@r.message(F.text == BTN_ADMIN, admin_only)
async def btn_admin(m: Message, state: FSMContext):
    await reset(state)
    await m.answer(ADM_TEXT, reply_markup=adm_kb)


@r.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery, state: FSMContext):
    await reset(state)
    await show(c, QUICK_TEXT, menu_kb(c.from_user.id))


@r.message(Command("help"))
@r.message(F.text == BTN_HELP)
async def cmd_help(m: Message, state: FSMContext):
    await reset(state)
    await m.answer(HELP_TEXT, reply_markup=KB([B("⬅️ Menu", "menu")]))


@r.callback_query(F.data == "help")
async def cb_help(c: CallbackQuery):
    await show(c, HELP_TEXT, KB([B("⬅️ Menu", "menu")]))


@r.message(Command("cancel"))
@r.callback_query(F.data == "cancel")
async def cancel(ev, state: FSMContext):
    await reset(state)
    await show(ev, "✖️ <b>Cancelled.</b>\nNothing was changed.", menu_kb(ev.from_user.id))


@r.message(Command("new"))
@r.message(F.text == BTN_CREATE)
async def cmd_new(m: Message, state: FSMContext):
    await reset(state)
    await m.answer(MODE_TEXT, reply_markup=mode_kb())


@r.callback_query(F.data == "new")
async def cb_new(c: CallbackQuery, state: FSMContext):
    await reset(state)
    await show(c, MODE_TEXT, mode_kb())


@r.message(Command("mysites"))
@r.message(F.text == BTN_MY)
@r.callback_query(F.data == "my")
async def my_sites(ev, state: FSMContext):
    await reset(state)
    uid = ev.from_user.id
    u = await db.users.find_one({"uid": uid}, {"unlocked": 1}) or {}
    q = {"$or": [{"owner": uid}, {"sid": {"$in": u.get("unlocked", [])}}]}
    items = await db.sites.find(q).sort("updated", -1).to_list(30)
    rows = [[B(f"🌐 {s['title'][:24]} · /{s['slug']}", f"s:{s['sid']}")] for s in items]
    rows.append([B("➕ New", "new"), B("⬅️ Menu", "menu")])
    text = (f"<b>📂 My Websites</b>  ({len(items)})\n{DIV}\nTap a site to manage it." if items else
            f"<b>📂 My Websites</b>\n{DIV}\nYou have no websites yet.\nSend me some code or a file to create your first one!")
    await show(ev, text, KB(*rows))


@r.message(F.text == BTN_EDIT)
@r.callback_query(F.data == "editcode")
async def ask_code(ev, state: FSMContext):
    await reset(state)
    await state.set_state(S.edit_code)
    await show(ev, f"🔑 <b>Edit by Code</b>\n{DIV}\nSend the website's <b>edit code</b>.\nIt looks like <code>EC-1A2B3C4D5E</code>.", cancel_kb)


async def try_code(m: Message, state: FSMContext, code: str):
    site = await db.sites.find_one({"code": code.strip().upper()})
    if not site:
        return await m.answer(oops("Invalid edit code", "No website matches that code.",
                                   "Check for typos — it starts with <code>EC-</code> and has 10 letters/digits."),
                              reply_markup=cancel_kb)
    await db.users.update_one({"uid": m.from_user.id}, {"$addToSet": {"unlocked": site["sid"]}})
    await state.clear()
    await send_card(m, site, banner="🔓 <b>Access granted</b>\n\n")


@r.message(StateFilter(S.edit_code), plain_text)
async def edit_code_in(m: Message, state: FSMContext):
    await try_code(m, state, m.text)


@r.message(Command("edit"))
async def cmd_edit(m: Message, command: CommandObject, state: FSMContext):
    await reset(state)
    if command.args:
        return await try_code(m, state, command.args)
    await ask_code(m, state)


# ═════════════════════════ CREATE (guided) ═════════════════════════
@r.callback_query(F.data.startswith("m:"))
async def cb_mode(c: CallbackQuery, state: FSMContext):
    if not await quota_ok(c.from_user.id):
        return await c.answer(f"Website limit reached ({MAX_SITES}). Delete one first.", show_alert=True)
    mode = c.data.split(":")[1]
    if mode == "paste":
        await state.set_state(S.paste_new)
        await show(c, f"📝 <b>Paste Code</b>\n{DIV}\nSend your code as a message.\n\n"
                      "<b>Several files?</b> Use separators:\n<code>### index.html\n...\n### style.css\n...</code>\n\n"
                      "<i>Code longer than ~4000 characters? Upload it as a file instead.</i>", cancel_kb)
    elif mode == "single":
        await state.set_state(S.single_new)
        await show(c, f"📄 <b>Single File / ZIP</b>\n{DIV}\nSend one file as a <b>File</b>:\n"
                      ".html · .css · .js · .pdf · images · or a <b>.zip</b> with a whole site.", cancel_kb)
    else:
        site = await new_site(c.from_user.id)
        await state.set_state(S.multi)
        await state.update_data(sid=site["sid"], fresh=True)
        await show(c, f"📦 <b>Multiple Files</b>\n{DIV}\nSend all your files — HTML, CSS, JS, images, fonts or a <b>.zip</b>.\n"
                      "Send them as <b>File</b> (not Photo) to keep names and quality.\n\nPress <b>Done</b> when finished.",
                   done_kb(site["sid"]))


# ═════════════════════════ CREATE from code / files (works with or without buttons) ═════════════════════════
@r.message(StateFilter(S.paste_new, S.single_new, None), plain_text)
async def create_from_text(m: Message, state: FSMContext):
    cur = await state.get_state()
    if cur is None and not looks_like_code(m.text):
        return await m.answer(NOT_CODE_TEXT, reply_markup=menu_kb(m.from_user.id))
    if not await quota_ok(m.from_user.id):
        return await m.answer(limit_msg())
    site = await new_site(m.from_user.id)
    try:
        for name, content in parse_blocks(m.text).items():
            await put(site["sid"], name, content.encode("utf-8"))
    except ValueError as e:
        await drop_site_data(site["sid"])
        return await m.answer(oops("Could not create the website", esc(e), "Fix the problem and send your code again."),
                              reply_markup=cancel_kb)
    await state.clear()
    await finish_new(m, site)


@r.message(StateFilter(S.paste_new, S.single_new, None), F.document)
async def create_from_doc(m: Message, state: FSMContext, bot: Bot):
    uid, d = m.from_user.id, m.document
    name = d.file_name or "file"
    gid = m.media_group_id
    new = False
    async with ALBUM_LOCK:
        for k, (_, t) in list(ALBUMS.items()):
            if time.time() - t > 900:
                ALBUMS.pop(k, None)
        if gid and gid in ALBUMS:
            site = await db.sites.find_one({"sid": ALBUMS[gid][0]})
        else:
            if not await quota_ok(uid):
                return await m.answer(limit_msg())
            site = await new_site(uid)
            new = True
            if gid:
                ALBUMS[gid] = (site["sid"], time.time())
    if not site:
        return await m.answer(oops("Website not found", "This upload belongs to a website that was removed.",
                                   "Send the files again."))
    sid = site["sid"]
    try:
        data = await read_doc(bot, d)
        if name.lower().endswith(".zip"):
            n, sk = await add_zip(sid, data)
            note = f"📦 Extracted <b>{n}</b> file(s)" + (f" · skipped {sk}" if sk else "")
        else:
            fname = "index.html" if (new and not gid and name.lower().endswith((".html", ".htm"))) else name
            await put(sid, fname, data)
            note = f"✅ Saved <code>{esc(fname)}</code>"
    except (ValueError, zipfile.BadZipFile) as e:
        if not await db.files.count_documents({"sid": sid}):
            await drop_site_data(sid)
            if gid:
                ALBUMS.pop(gid, None)
        title, why, fix, _ = explain(e)
        return await m.answer(oops(f"Could not use '{name}'", why, fix), reply_markup=cancel_kb)
    if new:
        await state.clear()
        await finish_new(m, site)
    else:
        await m.reply(note, reply_markup=KB([B("🛠 Manage website", f"s:{sid}")]))


@r.message(StateFilter(S.paste_new, S.single_new))
async def wrong_input_create(m: Message):
    await m.answer(oops("Unsupported content", "I need <b>code as text</b> or a <b>file</b> here.",
                        "Send your code, or attach a file as <b>File</b> (not Photo)."), reply_markup=cancel_kb)


# ═════════════════════════ multi-file collector (create + upload more) ═════════════════════════
@r.message(StateFilter(S.multi), F.document)
async def multi_doc(m: Message, state: FSMContext, bot: Bot):
    sid = (await state.get_data())["sid"]
    name = m.document.file_name or "file"
    try:
        data = await read_doc(bot, m.document)
        if name.lower().endswith(".zip"):
            n, sk = await add_zip(sid, data)
            txt = f"📦 Extracted <b>{n}</b> file(s)" + (f" · skipped {sk}" if sk else "")
        else:
            await put(sid, name, data)
            txt = f"✅ Saved <code>{esc(name)}</code>"
    except (ValueError, zipfile.BadZipFile) as e:
        _, why, fix, _n = explain(e)
        txt = oops(f"Could not use '{name}'", why, fix)
    await m.reply(txt, reply_markup=done_kb(sid))


@r.message(StateFilter(S.multi), F.photo)
async def multi_photo(m: Message, state: FSMContext, bot: Bot):
    sid = (await state.get_data())["sid"]
    ph = m.photo[-1]
    try:
        name = f"image_{ph.file_unique_id}.jpg"
        await put(sid, name, await read_doc(bot, ph))
        txt = f"✅ Saved <code>{name}</code>"
    except ValueError as e:
        _, why, fix, _n = explain(e)
        txt = oops("Could not save the image", why, fix)
    await m.reply(txt, reply_markup=done_kb(sid))


@r.message(StateFilter(S.multi))
async def multi_hint(m: Message, state: FSMContext):
    sid = (await state.get_data())["sid"]
    await m.answer(oops("Files only", "In this step I only accept <b>files</b>.",
                        "Send files as <b>File</b>, then press <b>Done</b>."), reply_markup=done_kb(sid))


@r.callback_query(F.data.startswith("done:"))
async def cb_done(c: CallbackQuery, state: FSMContext):
    sid = c.data.split(":")[1]
    d = await state.get_data()
    site = await db.sites.find_one({"sid": sid})
    if not site:
        return await c.answer("This website no longer exists.", show_alert=True)
    if not await db.files.count_documents({"sid": sid}):
        if d.get("fresh"):
            await db.sites.delete_one({"sid": sid})
            await state.clear()
            return await show(c, "ℹ️ No files were received, so nothing was created.", menu_kb(c.from_user.id))
        return await c.answer("No files uploaded yet.", show_alert=True)
    await state.clear()
    await refresh_title(sid)
    site = await db.sites.find_one({"sid": sid})
    await send_card(c, site, banner="✨ <b>Your website is live!</b>\n\n" if d.get("fresh") else "✅ <b>Files updated</b>\n\n")
    if d.get("fresh") and site["owner"] not in ADMINS and ADMINS:
        try:
            await c.bot.send_message(min(ADMINS), f"🆕 <b>New site</b> by <code>{c.from_user.id}</code>\n{esc(site_url(site))}")
        except Exception:  # noqa
            pass


# ═════════════════════════ manage a site ═════════════════════════
@r.callback_query(F.data.startswith("s:"))
async def cb_site(c: CallbackQuery, state: FSMContext):
    await reset(state)
    site = await auth(c, c.data.split(":")[1])
    if site:
        await send_card(c, site)


@r.callback_query(F.data.startswith("pe:"))
async def cb_pe(c: CallbackQuery, state: FSMContext):
    site = await auth(c, c.data.split(":")[1])
    if not site:
        return
    await state.set_state(S.paste_edit)
    await state.update_data(sid=site["sid"])
    await show(c, f"📝 <b>Paste Code</b>\n{DIV}\nSend code to replace <code>index.html</code>.\n\n"
                  "To update other files use separators:\n<code>### style.css\nbody{...}\n### script.js\n...</code>", cancel_kb)


@r.message(StateFilter(S.paste_edit), plain_text)
async def paste_edit(m: Message, state: FSMContext):
    sid = (await state.get_data())["sid"]
    names = []
    try:
        for name, content in parse_blocks(m.text).items():
            await put(sid, name, content.encode("utf-8"))
            names.append(name)
    except ValueError as e:
        return await m.answer(oops("Update failed", esc(e), "Fix the problem and send the code again."), reply_markup=cancel_kb)
    await state.clear()
    await refresh_title(sid)
    await send_card(m, await db.sites.find_one({"sid": sid}),
                    banner="✅ <b>Updated:</b> " + ", ".join(f"<code>{esc(n)}</code>" for n in names) + "\n\n")


@r.callback_query(F.data.startswith("up:"))
async def cb_up(c: CallbackQuery, state: FSMContext):
    site = await auth(c, c.data.split(":")[1])
    if not site:
        return
    await state.set_state(S.multi)
    await state.update_data(sid=site["sid"], fresh=False)
    await show(c, f"📤 <b>Upload Files</b>\n{DIV}\nSend files to add or replace (same name = replaced). ZIP supported.\n"
                  "Press <b>Done</b> when finished.", done_kb(site["sid"]))


async def files_view(c: CallbackQuery, site: dict):
    items = await db.files.find({"sid": site["sid"]}, {"path": 1, "size": 1}).sort("path", 1).to_list(200)
    lines = [f"📄 <code>{esc(i['path'])}</code> · {fmt_size(i['size'])}" for i in items[:40]]
    rows = [[B(f"🗑 {i['path'][:40]}", f"rm:{site['sid']}:{n}")] for n, i in enumerate(items[:25])]
    rows.append([B("⬅️ Back", f"s:{site['sid']}")])
    text = f"<b>📁 Files</b>  ({len(items)})\n{DIV}\n" + ("\n".join(lines) or "No files.")
    if len(items) > 25:
        text += "\n\n<i>Delete buttons are shown for the first 25 files.</i>"
    await show(c, text, KB(*rows))


@r.callback_query(F.data.startswith("fl:"))
async def cb_fl(c: CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if site:
        await files_view(c, site)


@r.callback_query(F.data.startswith("rm:"))
async def cb_rm(c: CallbackQuery):
    _, sid, idx = c.data.split(":")
    site = await auth(c, sid)
    if not site:
        return
    items = await db.files.find({"sid": sid}, {"path": 1}).sort("path", 1).to_list(200)
    if int(idx) < len(items):
        await db.files.delete_one({"_id": items[int(idx)]["_id"]})
        await db.sites.update_one({"sid": sid}, {"$set": {"updated": now()}})
    await files_view(c, site)


@r.callback_query(F.data.startswith("sl:"))
async def cb_sl(c: CallbackQuery, state: FSMContext):
    site = await auth(c, c.data.split(":")[1])
    if not site:
        return
    await state.set_state(S.slug)
    await state.update_data(sid=site["sid"])
    await show(c, f"🔗 <b>Short Link</b>\n{DIV}\nCurrent: <code>/s/{site['slug']}/</code>\n\n"
                  "Send a new name — 3 to 32 characters: <b>a-z, 0-9, hyphen</b>.", cancel_kb)


@r.message(StateFilter(S.slug), plain_text)
async def slug_in(m: Message, state: FSMContext):
    sid = (await state.get_data())["sid"]
    slug = m.text.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}[a-z0-9]", slug) or slug in RESERVED_SLUGS:
        return await m.answer(oops("Invalid short link", f"<code>{esc(slug[:40])}</code> is not allowed.",
                                   "Use 3–32 characters: letters a-z, digits, hyphen. Don't start or end with a hyphen."),
                              reply_markup=cancel_kb)
    if await db.sites.find_one({"slug": slug, "sid": {"$ne": sid}}):
        return await m.answer(oops("Name already taken", f"<code>{esc(slug)}</code> is used by another website.",
                                   "Try a different name."), reply_markup=cancel_kb)
    await db.sites.update_one({"sid": sid}, {"$set": {"slug": slug, "updated": now()}})
    await state.clear()
    await send_card(m, await db.sites.find_one({"sid": sid}), banner="✅ <b>Short link updated</b>\n\n")


@r.callback_query(F.data.startswith("dm:"))
async def cb_dm(c: CallbackQuery, state: FSMContext):
    site = await auth(c, c.data.split(":")[1])
    if not site:
        return
    await state.set_state(S.domain)
    await state.update_data(sid=site["sid"])
    rows = [[B("✖️ Cancel", "cancel")]]
    cur = ""
    if site.get("domain"):
        cur = f"Current: <code>{esc(site['domain'])}</code>\n\n"
        rows.insert(0, [B("🗑 Remove domain", f"dmrm:{site['sid']}")])
    await show(c, f"🌐 <b>Custom Domain</b>\n{DIV}\n{cur}Send your domain, e.g. <code>mysite.com</code> or <code>www.mysite.com</code>.\n\n"
                  f"Then add this DNS record at your domain provider:\n<code>CNAME  →  {BASE_HOST}</code>\n"
                  "<i>(Root domain? use ALIAS/ANAME, or the A record shown in your Render dashboard.)</i>", KB(*rows))


@r.message(StateFilter(S.domain), plain_text)
async def domain_in(m: Message, state: FSMContext):
    sid = (await state.get_data())["sid"]
    d = re.sub(r"^https?://", "", m.text.strip().lower()).split("/")[0]
    if not re.fullmatch(r"([a-z0-9-]{1,63}\.)+[a-z]{2,24}", d) or d == BASE_HOST or d.endswith("." + BASE_HOST):
        return await m.answer(oops("Invalid domain", f"<code>{esc(d[:60])}</code> is not a valid custom domain.",
                                   "Send something like <code>mysite.com</code> (not an onrender.com address)."),
                              reply_markup=cancel_kb)
    if await db.sites.find_one({"domain": d, "sid": {"$ne": sid}}):
        return await m.answer(oops("Domain already used", "That domain is connected to another website.",
                                   "Use a different domain or remove it from the other site."), reply_markup=cancel_kb)
    old = await db.sites.find_one({"sid": sid})
    if old.get("domain") and old["domain"] != d:
        await render_domain(False, old["domain"])
    await db.sites.update_one({"sid": sid}, {"$set": {"domain": d, "updated": now()}})
    st = await render_domain(True, d)
    if st in (200, 201):
        note = "✅ Added on Render automatically — SSL is issued once DNS verifies."
    elif st is None:
        note = "⚠️ Also add this domain in <b>Render → your service → Settings → Custom Domains</b> so SSL works."
    else:
        note = f"⚠️ Render API replied {st}. Add the domain manually in Render → Custom Domains."
    await state.clear()
    await send_card(m, await db.sites.find_one({"sid": sid}),
                    banner=f"✅ <b>Domain saved</b>\nDNS: <code>CNAME → {BASE_HOST}</code>\n{note}\n\n")


@r.callback_query(F.data.startswith("dmrm:"))
async def cb_dmrm(c: CallbackQuery, state: FSMContext):
    site = await auth(c, c.data.split(":")[1])
    if not site:
        return
    if site.get("domain"):
        await render_domain(False, site["domain"])
        await db.sites.update_one({"sid": site["sid"]}, {"$unset": {"domain": ""}})
    await state.clear()
    await send_card(c, await db.sites.find_one({"sid": site["sid"]}), banner="✅ <b>Domain removed</b>\n\n")


@r.message(StateFilter(S.edit_code, S.paste_edit, S.slug, S.domain))
async def need_text(m: Message):
    await m.answer(oops("Text needed", "I'm waiting for a <b>text message</b> here.", "Type your answer, or press Cancel."),
                   reply_markup=cancel_kb)


@r.callback_query(F.data.startswith("code:"))
async def cb_code(c: CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if not site:
        return
    await c.message.answer(f"🔑 <b>Edit code</b> — {esc(site['title'])}\n{DIV}\n<code>{site['code']}</code>\n\n"
                           "Anyone with this code can edit the site. Regenerate it if it leaked.",
                           reply_markup=KB([B("🔄 Regenerate", f"regen:{site['sid']}")]))
    await c.answer()


@r.callback_query(F.data.startswith("regen:"))
async def cb_regen(c: CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if not site:
        return
    code = "EC-" + secrets.token_hex(5).upper()
    await db.sites.update_one({"sid": site["sid"]}, {"$set": {"code": code}})
    await db.users.update_many({"uid": {"$ne": site["owner"]}}, {"$pull": {"unlocked": site["sid"]}})
    await c.message.edit_text(f"🔑 <b>New edit code</b>\n{DIV}\n<code>{code}</code>\n\nThe old code and other editors' access were revoked.")
    await c.answer()


@r.callback_query(F.data.startswith("del:"))
async def cb_del(c: CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if site:
        await show(c, f"🗑 <b>Delete website?</b>\n{DIV}\n<b>{esc(site['title'])}</b> will be removed permanently.\nThis cannot be undone.",
                   KB([B("✅ Yes, delete", f"delok:{site['sid']}"), B("↩️ No", f"s:{site['sid']}")]))


@r.callback_query(F.data.startswith("delok:"))
async def cb_delok(c: CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if site:
        await delete_site(site)
        await show(c, "✅ <b>Website deleted.</b>", KB([B("📂 My Sites", "my"), B("⬅️ Menu", "menu")]))


# ═════════════════════════ admin ═════════════════════════
async def stats_text():
    tu, bu = await db.users.count_documents({}), await db.users.count_documents({"banned": True})
    day = now() - 86400
    nu = await db.users.count_documents({"joined": {"$gt": day}})
    ts, ns = await db.sites.count_documents({}), await db.sites.count_documents({"created": {"$gt": day}})
    nf = await db.files.count_documents({})
    agg = await db.files.aggregate([{"$group": {"_id": None, "s": {"$sum": "$size"}}}]).to_list(1)
    views = await db.sites.aggregate([{"$group": {"_id": None, "v": {"$sum": "$views"}}}]).to_list(1)
    dom = await db.sites.count_documents({"domain": {"$type": "string"}})
    return (f"<b>📊 Statistics</b>\n{DIV}\n👥 Users: <b>{tu}</b>  (+{nu} today · 🚫 {bu})\n"
            f"🌐 Sites: <b>{ts}</b>  (+{ns} today)\n🌍 Custom domains: {dom}\n"
            f"📁 Files: {nf}  ·  💾 {fmt_size(agg[0]['s'] if agg else 0)}\n👁 Total views: {views[0]['v'] if views else 0}")


adm_kb = KB([B("📊 Stats", "adm:stats"), B("👥 Users", "adm:users")],
            [B("🌐 All Sites", "adm:sites"), B("📢 Broadcast", "adm:bc")],
            [B("⬅️ Menu", "menu")])
ADM_TEXT = (f"<b>🛠 Admin Panel</b>\n{DIV}\n/stats · /users · /sites · /site slug\n/ban id · /unban id\n"
            "/delsite slug · /broadcast text (or reply to a message)")


@r.callback_query(F.data == "adm", admin_only)
@r.message(Command("admin"), admin_only)
async def adm(ev, state: FSMContext):
    await reset(state)
    await show(ev, ADM_TEXT, adm_kb)


@r.callback_query(F.data == "adm:stats", admin_only)
@r.message(Command("stats"), admin_only)
async def adm_stats(ev):
    await show(ev, await stats_text(), KB([B("🔄 Refresh", "adm:stats"), B("⬅️ Back", "adm")]))


@r.callback_query(F.data == "adm:users", admin_only)
@r.message(Command("users"), admin_only)
async def adm_users(ev):
    items = await db.users.find().sort("last", -1).to_list(20)
    lines = [f"{'🚫' if u.get('banned') else '👤'} <code>{u['uid']}</code> {esc(u.get('name', ''))}"
             f"{' @' + esc(u['username']) if u.get('username') else ''}" for u in items]
    await show(ev, f"<b>👥 Recent users</b>\n{DIV}\n" + "\n".join(lines), KB([B("⬅️ Back", "adm")]))


@r.callback_query(F.data == "adm:sites", admin_only)
@r.message(Command("sites"), admin_only)
async def adm_sites(ev):
    items = await db.sites.find().sort("created", -1).to_list(20)
    rows = [[B(f"/{s['slug']} · {s['title'][:22]} · {s['owner']}", f"s:{s['sid']}")] for s in items]
    rows.append([B("⬅️ Back", "adm")])
    await show(ev, f"<b>🌐 Latest sites</b>  ({await db.sites.count_documents({})} total)", KB(*rows))


@r.message(Command("site"), admin_only)
async def adm_site(m: Message, command: CommandObject):
    s = await db.sites.find_one({"slug": (command.args or "").strip().lower()})
    if not s:
        return await m.answer("Site not found. Usage: /site slug")
    await send_card(m, s)


@r.message(Command("delsite"), admin_only)
async def adm_delsite(m: Message, command: CommandObject):
    s = await db.sites.find_one({"slug": (command.args or "").strip().lower()})
    if not s:
        return await m.answer("Site not found. Usage: /delsite slug")
    await delete_site(s)
    await m.answer(f"🗑 Deleted <code>/{s['slug']}</code>")


@r.message(Command("ban"), admin_only)
@r.message(Command("unban"), admin_only)
async def adm_ban(m: Message, command: CommandObject):
    ban = command.command == "ban"
    arg = (command.args or "").split()
    if not arg or not arg[0].isdigit():
        return await m.answer(f"Usage: /{command.command} user_id")
    uid = int(arg[0])
    if uid in ADMINS:
        return await m.answer("You cannot ban an admin.")
    res = await db.users.update_one({"uid": uid}, {"$set": {"banned": ban}})
    if not res.matched_count:
        return await m.answer("User not found.")
    await m.answer(("🚫 Banned " if ban else "✅ Unbanned ") + f"<code>{uid}</code>")


async def do_broadcast(bot: Bot, admin: int, text=None, chat=None, mid=None):
    ok = fail = 0
    try:
        async for u in db.users.find({"banned": {"$ne": True}}, {"uid": 1}):
            for _ in range(2):
                try:
                    if text:
                        await bot.send_message(u["uid"], text)
                    else:
                        await bot.copy_message(u["uid"], chat, mid)
                    ok += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except Exception:  # noqa
                    fail += 1
                    break
            await asyncio.sleep(0.05)
        await bot.send_message(admin, f"📢 <b>Broadcast finished</b>\n✅ Sent: {ok}\n❌ Failed: {fail}")
    except Exception as e:  # noqa
        log.exception("broadcast failed")
        await bot.send_message(admin, f"📢 Broadcast stopped by an error: <code>{esc(type(e).__name__)}: {esc(e)[:200]}</code>\nSent so far: {ok}")


@r.message(Command("broadcast"), admin_only)
async def adm_bc(m: Message, command: CommandObject, bot: Bot):
    if m.reply_to_message:
        asyncio.create_task(do_broadcast(bot, m.from_user.id, chat=m.chat.id, mid=m.reply_to_message.message_id))
    elif command.args:
        asyncio.create_task(do_broadcast(bot, m.from_user.id, text=command.args))
    else:
        return await m.answer("Usage: /broadcast text — or reply to any message with /broadcast")
    await m.answer("📢 Broadcast started…")


@r.callback_query(F.data == "adm:bc", admin_only)
async def adm_bc_btn(c: CallbackQuery, state: FSMContext):
    await state.set_state(S.broadcast)
    await show(c, "📢 <b>Broadcast</b>\nSend the message (text, photo, anything). It will be copied to all users.", cancel_kb)


@r.message(StateFilter(S.broadcast), admin_only)
async def adm_bc_msg(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    asyncio.create_task(do_broadcast(bot, m.from_user.id, chat=m.chat.id, mid=m.message_id))
    await m.answer("📢 Broadcast started…")


# ═════════════════════════ fallbacks (nothing is ever ignored silently) ═════════════════════════
@r.message(StateFilter(None), F.photo)
async def direct_photo(m: Message):
    await m.answer(oops("Photos are compressed", "Telegram shrinks photos, so I can't use them as website files.",
                        "Send the image as a <b>File</b> (attach → File), or put it in a ZIP."),
                   reply_markup=menu_kb(m.from_user.id))


@r.message(StateFilter(None))
async def direct_other(m: Message):
    if m.text and m.text.startswith("/"):
        return await m.answer("❓ <b>Unknown command.</b>\nUse /start or the keyboard below.", reply_markup=menu_kb(m.from_user.id))
    await m.answer(oops("I can't build a site from that", "Only <b>code</b> and <b>files</b> work here.",
                        "Send HTML code, a file, or a ZIP — or use the buttons."), reply_markup=menu_kb(m.from_user.id))


@r.callback_query()
async def stale_callback(c: CallbackQuery):
    await c.answer("This button is no longer active. Press /start to open the menu.", show_alert=True)


# ═════════════════════════ global error handler (reports every error) ═════════════════════════
@r.errors()
async def on_error(event: ErrorEvent, bot: Bot):
    exc = event.exception
    upd = event.update
    ref = secrets.token_hex(3)
    cb = upd.callback_query
    uid = None
    if upd.message and upd.message.from_user:
        uid = upd.message.from_user.id
    elif cb:
        uid = cb.from_user.id
    log.error("Handler error #%s (user %s): %s", ref, uid, exc, exc_info=exc)

    if isinstance(exc, TelegramForbiddenError):
        return True  # user blocked the bot — nothing to tell
    if isinstance(exc, TelegramBadRequest) and "not modified" in str(exc).lower():
        if cb:
            try:
                await cb.answer()
            except Exception:  # noqa
                pass
        return True

    title, why, fix, notify = explain(exc)
    if cb:
        try:
            await cb.answer("⚠️ Something went wrong — details sent below.")
        except Exception:  # noqa
            pass
    if uid:
        try:
            await bot.send_message(uid, oops(title, why, fix) + f"\n\n<code>Ref #{ref}</code>",
                                   reply_markup=KB([B("⬅️ Menu", "menu")]))
        except Exception:  # noqa
            log.exception("could not deliver error message to user")
    if notify:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-2500:]
        for a in ADMINS:
            try:
                await bot.send_message(a, f"🚨 <b>Error #{ref}</b>\nUser: <code>{uid}</code>\n<pre>{esc(tb)}</pre>")
            except Exception:  # noqa
                pass
    return True


# ═════════════════════════ startup ═════════════════════════
async def on_startup(bot: Bot):
    global BOT_USERNAME
    try:
        await init_db()
        me = await bot.get_me()
        BOT_USERNAME = me.username or ""
        await bot.set_webhook(f"{WEBHOOK_URL}/webhook", secret_token=WEBHOOK_SECRET,
                              allowed_updates=["message", "callback_query"])
    except TelegramBadRequest as e:
        log.critical("❌ Telegram rejected the setup: %s. Check BOT_TOKEN and WEBHOOK_URL.", e)
        raise SystemExit(1)
    except Exception as e:
        log.critical("❌ Startup failed: %s: %s", type(e).__name__, e)
        raise SystemExit(1)
    base = [BotCommand(command="start", description="Open the main menu"),
            BotCommand(command="new", description="Create a website"),
            BotCommand(command="mysites", description="My websites"),
            BotCommand(command="edit", description="Edit by code"),
            BotCommand(command="help", description="How it works"),
            BotCommand(command="cancel", description="Cancel current action")]
    try:
        await bot.set_my_commands(base)
        for a in ADMINS:
            await bot.set_my_commands(base + [BotCommand(command="admin", description="Admin panel"),
                                              BotCommand(command="stats", description="Statistics"),
                                              BotCommand(command="broadcast", description="Broadcast a message")],
                                      scope=BotCommandScopeChat(chat_id=a))
    except Exception as e:  # noqa
        log.warning("set_my_commands failed: %s", e)
    for a in ADMINS:
        try:
            await bot.send_message(a, f"✅ <b>Bot is online</b>\n@{esc(BOT_USERNAME)} · {esc(WEBHOOK_URL)}")
        except Exception:  # noqa
            pass
    log.info("Bot @%s ready · %s", BOT_USERNAME, WEBHOOK_URL)


async def on_shutdown(bot: Bot):
    await bot.session.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not ADMINS:
        log.warning("ADMIN_ID is not set — admin tools and error reports are disabled")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(Guard())
    dp.include_router(r)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application(middlewares=[web_error_middleware], client_max_size=1024 ** 2)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path="/webhook")
    add_routes(app)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()

"""
Web Maker Bot - FINAL FIXED - Part 1/4
"""
import asyncio, html as _html, io, logging, mimetypes, os, re, secrets, time, traceback, zipfile
from urllib.parse import urlparse
import aiohttp
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, CallbackQuery, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from bson.binary import Binary
from pymongo.errors import PyMongoError

# Config import - tera alag config.py hai toh ye use hoga
from config import *
from database import db, init_db

log = logging.getLogger("webmaker")

for _ext, _mt in {".webp":"image/webp",".woff2":"font/woff2",".woff":"font/woff",".mjs":"application/javascript",".svg":"image/svg+xml"}.items():
    mimetypes.add_type(_mt, _ext)

DIV = "━━━━━━━━━━━━━━━━"
BTN_CREATE = "➕ Create Website"
BTN_MY = "📂 My Websites"
BTN_EDIT = "✏️ Edit by Code"
BTN_HELP = "❓ Help"
BTN_ADMIN = "🛠 Admin Panel"

def now(): return int(time.time())
def esc(s): return _html.escape(str(s))
def fmt_size(n: int) -> str:
    if n < 1024: return f"{n} B"
    if n < 1048576: return f"{n/1024:.1f} KB"
    return f"{n/1048576:.1f} MB"
def clean_path(p: str):
    p = (p or "").replace("\\","/")
    parts = [x for x in p.split("/") if x not in ("",".")]
    if any(x==".." for x in parts): return None
    out="/".join(parts)
    return out if len(out)<=200 else None
def site_url(site: dict) -> str:
    return f"https://{site['domain']}/" if site.get("domain") else f"{WEBHOOK_URL}/s/{site['slug']}/"
def strip_fence(t: str) -> str:
    t=t.strip(); m=re.match(r"^```[\w+-]*\n(.*?)\n?```$", t, re.S); return m.group(1) if m else t
def parse_blocks(text: str) -> dict:
    text=text.strip(); parts=re.split(r"(?m)^###\s*([^\s]+)\s*$", text)
    if len(parts)==1: return {"index.html": strip_fence(text)}
    out={}
    for i in range(1,len(parts),2): out[parts[i]]=strip_fence(parts[i+1])
    return out
def looks_like_code(t: str) -> bool:
    s=(t or "").strip()
    if not s or s.startswith("/"): return False
    if re.search(r"(?m)^###\s*\S+\s*$", s) or s.startswith("```"): return True
    return bool(re.search(r"<\s*(html|head|body|div|style|script)", s, re.I))

async def site_size(sid: str) -> int:
    cur = db.files.aggregate([{"$match":{"sid":sid}},{"$group":{"_id":None,"s":{"$sum":"$size"}}}])
    r = await cur.to_list(length=1)
    return r[0]["s"] if r else 0# Part 2/4
async def put(sid: str, path: str, data: bytes, check: bool=True):
    p=clean_path(path)
    if not p: raise ValueError(f"'{path}' invalid")
    if len(data)>MAX_FILE: raise ValueError(f"{path} too big")
    if check:
        if not await db.sites.find_one({"sid":sid},{"_id":1}): raise ValueError("Site gone")
        old=await db.files.find_one({"sid":sid,"path":p},{"size":1})
        total=await site_size(sid)-(old["size"] if old else 0)
        if total+len(data)>MAX_SITE: raise ValueError("Site limit")
    mime=mimetypes.guess_type(p)[0] or "application/octet-stream"
    await db.files.update_one({"sid":sid,"path":p},{"$set":{"data":Binary(data),"mime":mime,"size":len(data),"ts":now()}},upsert=True)
    await db.sites.update_one({"sid":sid},{"$set":{"updated":now()}})

async def add_zip(sid: str, data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos=[i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX")]
        if not infos: raise ValueError("ZIP empty")
        if not await db.sites.find_one({"sid":sid},{"_id":1}): raise ValueError("Site gone")
        cnt=0
        for i in infos:
            try: await put(sid,i.filename,z.read(i),check=False); cnt+=1
            except: pass
        return cnt,0

async def new_site(owner: int):
    sid=secrets.token_hex(6); alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        slug="".join(secrets.choice(alphabet) for _ in range(6))
        if slug not in RESERVED_SLUGS and not await db.sites.find_one({"slug":slug},{"_id":1}): break
    doc={"sid":sid,"slug":slug,"code":"EC-"+secrets.token_hex(5).upper(),"owner":owner,"title":"Untitled","created":now(),"updated":now(),"views":0}
    await db.sites.insert_one(doc); return doc

async def refresh_title(sid: str):
    f=await db.files.find_one({"sid":sid,"path":"index.html"}) or await db.files.find_one({"sid":sid,"path":{"$regex":r"\.html?$"}})
    if f:
        m=re.search(rb"<title[^>]*>(.*?)</title>", bytes(f["data"][:20000]), re.I|re.S)
        if m: t=m.group(1).decode("utf8","ignore").strip()[:60]; await db.sites.update_one({"sid":sid},{"$set":{"title":t}})

async def delete_site(site: dict):
    await db.files.delete_many({"sid":site["sid"]}); await db.sites.delete_one({"sid":site["sid"]})

def oops(title, why, fix=""): return f"⚠️ <b>{esc(title)}</b>\n{why}\n\n{fix}"
def explain(e):
    if isinstance(e, zipfile.BadZipFile): return ("Bad ZIP","Corrupted ZIP","Re-upload",False)
    if isinstance(e, ValueError): return ("Invalid",esc(e),"Fix",False)
    return (type(e).__name__,esc(e)[:200],"Try again",True)

# ---------- WEB FIXED ----------
_PAGE = "<html><body><h1>%(code)s</h1><h2>%(title)s</h2><p>%(msg)s</p></body></html>"
def page(status, code, title, msg, extra=""): return web.Response(text=_PAGE % {"code":code,"title":title,"msg":msg,"extra":extra}, status=status, content_type="text/html")
def not_found(): return page(404,"404","Not found","Page not found")

async def serve_site(site: dict, tail: str, is_dir: bool):
    p=clean_path(tail);
    if p is None: return not_found()
    cands=[p+".html",p+"/index.html"] if p else ["index.html","index.htm"]
    if p: cands.insert(0,p)
    f=None
    for c in cands:
        f=await db.files.find_one({"sid":site["sid"],"path":c})
        if f: break
    if not f and not p: f=await db.files.find_one({"sid":site["sid"]})
    if not f: return not_found()
    if not p: asyncio.create_task(db.sites.update_one({"sid":site["sid"]},{"$inc":{"views":1}}))
    mime=f.get("mime") or "text/html"
    return web.Response(body=bytes(f["data"]), content_type=mime)

def _req_host(request): return request.host.split(":")[0].lower()
async def _site_by_host(host: str):
    s=await db.sites.find_one({"domain":host})
    if not s and host.startswith("www."): s=await db.sites.find_one({"domain":host[4:]})
    return s

async def h_health(request): return web.json_response({"ok":True})

async def h_site_redirect(request):
    q=f"?{request.query_string}" if request.query_string else ""
    raise web.HTTPFound(f"/s/{request.match_info['slug']}/{q}")

async def h_site(request):
    site=await db.sites.find_one({"slug":request.match_info["slug"].lower()})
    if not site: return not_found()
    return await serve_site(site, request.match_info["tail"], request.path.endswith("/"))

async def h_root(request):
    host=_req_host(request); tail=request.match_info["tail"]
    if host not in LOCAL_HOSTS:
        site=await _site_by_host(host)
        if site: return await serve_site(site, tail, request.path.endswith("/"))
        return page(404,"404","Domain not connected","Not connected")
    if tail=="": return page(200,"🌐","Web Maker","Bot running")
    return not_found()

@web.middleware
async def web_error_middleware(request, handler):
    try: return await handler(request)
    except web.HTTPException: raise
    except Exception as e:
        ref=secrets.token_hex(3); log.exception("web error #%s on %s", ref, request.path)
        if request.path=="/webhook": return web.Response(status=200, text="error logged")
        return page(500,"500","Error",f"Ref #{ref}")

def add_routes(app: web.Application):
    app.router.add_get("/health", h_health)
    app.router.add_get("/s/{slug}", h_site_redirect)
    app.router.add_get("/s/{slug}/{tail:.*}", h_site)
    app.router.add_get("/{tail:.*}", h_root)# Part 3/4
r=Router(); admin_only=F.from_user.id.in_(ADMINS)
ALBUMS={}; ALBUM_LOCK=asyncio.Lock()
class S(StatesGroup): paste_new=State(); single_new=State(); multi=State(); edit_code=State(); paste_edit=State(); slug=State(); domain=State(); broadcast=State()
def plain_text(m: Message): return bool(m.text) and not m.text.startswith("/")
def B(text,data=None,url=None):
    if url: return InlineKeyboardButton(text=text,url=url)
    return InlineKeyboardButton(text=text,callback_data=data)
def KB(*rows): return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])
def reply_kb(uid: int):
    rows=[[KeyboardButton(text=BTN_CREATE),KeyboardButton(text=BTN_MY)],[KeyboardButton(text=BTN_EDIT),KeyboardButton(text=BTN_HELP)]]
    if uid in ADMINS: rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True,is_persistent=True)
def menu_kb(uid: int):
    rows=[[B("➕ Create Website","new")],[B("📂 My Websites","my"),B("✏️ Edit by Code","editcode")],[B("❓ Help","help")]]
    if uid in ADMINS: rows.append([B("🛠 Admin Panel","adm")])
    return KB(*rows)
def mode_kb(): return KB([B("📝 Paste Code","m:paste")],[B("📄 Single File / ZIP","m:single")],[B("📦 Multiple Files","m:multi")],[B("⬅️ Menu","menu")])
cancel_kb=KB([B("✖️ Cancel","cancel")])
def done_kb(sid: str): return KB([B("✅ Done",f"done:{sid}"),B("✖️ Cancel","cancel")])

async def card(site: dict) -> str:
    n=await db.files.count_documents({"sid":site["sid"]}); size=await site_size(site["sid"])
    dom=f"\n🌍 Domain {esc(site['domain'])}" if site.get("domain") else ""
    return f"🌐 {esc(site['title'])}\nLink {site_url(site)}\nCode {site['code']}{dom}\n{n} files · {fmt_size(size)} · {site.get('views',0)} views"
def panel_kb(site: dict):
    sid=site["sid"]; rows=[]
    if site_url(site).startswith("https://"): rows.append([B("🌍 Open",url=site_url(site))])
    rows+=[[B("📝 Paste",f"pe:{sid}"),B("📤 Upload",f"up:{sid}")],[B("📁 Files",f"fl:{sid}"),B("🔗 Link",f"sl:{sid}")],[B("🌐 Domain",f"dm:{sid}"),B("🔑 Code",f"code:{sid}")],[B("🗑 Delete",f"del:{sid}"),B("⬅️ My Sites","my")]]
    return KB(*rows)

class Guard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u=data.get("event_from_user")
        if u and not u.is_bot:
            await db.users.update_one({"uid":u.id},{"$set":{"name":u.full_name,"username":u.username,"last":now()}, "$setOnInsert":{"joined":now(),"banned":False,"unlocked":[]}}, upsert=True)
        return await handler(event,data)

async def show(ev,text,kb=None):
    if isinstance(ev, CallbackQuery):
        try: await ev.answer()
        except: pass
        msg=ev.message
        if not isinstance(msg, Message): return await ev.bot.send_message(ev.from_user.id,text,reply_markup=kb)
        try: await msg.edit_text(text,reply_markup=kb)
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower(): return
            await msg.answer(text,reply_markup=kb)
    else: await ev.answer(text,reply_markup=kb)

async def reset(state: FSMContext):
    d=await state.get_data()
    if d.get("fresh") and d.get("sid") and not await db.files.count_documents({"sid":d["sid"]}):
        await db.sites.delete_one({"sid":d["sid"]})
    await state.clear()

async def send_card(ev, site, banner=""): await show(ev, banner+await card(site), panel_kb(site))
async def finish_new(ev, site):
    await refresh_title(site["sid"]); site=await db.sites.find_one({"sid":site["sid"]})
    await send_card(ev, site, banner="✨ Live!\n\n")

async def auth(c: CallbackQuery, sid: str):
    site=await db.sites.find_one({"sid":sid})
    if not site: await c.answer("Gone",show_alert=True); return None
    if c.from_user.id not in ADMINS and site.get("owner")!=c.from_user.id:
        u=await db.users.find_one({"uid":c.from_user.id},{"unlocked":1})
        if not u or sid not in u.get("unlocked",[]): await c.answer("No access",show_alert=True); return None
    return site

# Handlers part 3 continues in next part# Part 4/4 - remaining handlers (my sites, edit, admin, main)
WELCOME="Web Maker Bot"
HELP_TEXT="Help"
QUICK_TEXT="Quick Actions"
MODE_TEXT="Choose mode"
NOT_CODE_TEXT="Send code"
ADM_TEXT="Admin"
adm_kb=KB([B("📊 Stats","adm:stats")])

@r.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await reset(state); await m.answer(WELCOME, reply_markup=reply_kb(m.from_user.id)); await m.answer(QUICK_TEXT, reply_markup=menu_kb(m.from_user.id))

@r.message(Command("mysites"))
@r.message(F.text==BTN_MY)
@r.callback_query(F.data=="my")
async def my_sites(ev, state: FSMContext):
    await reset(state); uid=ev.from_user.id; u=await db.users.find_one({"uid":uid},{"unlocked":1}) or {}
    q={"$or":[{"owner":uid},{"sid":{"$in":u.get("unlocked",[])}}]}
    items=await db.sites.find(q).sort("updated",-1).to_list(30)
    rows=[[B(f"🌐 {s['title'][:24]} · /{s['slug']}", f"s:{s['sid']}")] for s in items]
    rows.append([B("➕ New","new"),B("⬅️ Menu","menu")])
    text=f"My Websites ({len(items)})" if items else "No sites"
    await show(ev,text,KB(*rows))

@r.callback_query(F.data.startswith("s:"))
async def cb_site(c: CallbackQuery, state: FSMContext):
    await reset(state); site=await auth(c,c.data.split(":")[1]);
    if site: await send_card(c, site)

@r.callback_query(F.data.startswith("fl:"))
async def cb_fl(c: CallbackQuery):
    site=await auth(c,c.data.split(":")[1])
    if site:
        items=await db.files.find({"sid":site["sid"]}).to_list(200)
        txt="\n".join([f"{i['path']} {fmt_size(i['size'])}" for i in items])
        await show(c, txt or "No files", KB([B("⬅️ Back",f"s:{site['sid']}")]))

# --- APP CREATION ---
async def create_app():
    await init_db()
    bot=Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp=Dispatcher(storage=MemoryStorage())
    dp.message.middleware(Guard()); dp.callback_query.middleware(Guard())
    dp.include_router(r)
    app=web.Application(middlewares=[web_error_middleware])
    add_routes(app)
    wh=SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
    wh.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    return app

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
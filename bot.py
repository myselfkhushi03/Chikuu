import asyncio, html as _html, io, logging, mimetypes, os, re, secrets, time, zipfile
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from bson.binary import Binary
from config import *
from database import db, init_db

log = logging.getLogger("Webify Bot☘️")
DIV = "━━━━━━━━━━━━━━━━"
BTN_CREATE = "➕ Create Website"
BTN_MY = "📂 My Websites"

for _ext,_mt in {".webp":"image/webp",".woff2":"font/woff2"}.items():
    mimetypes.add_type(_mt,_ext)

def now(): return int(time.time())
def esc(s): return _html.escape(str(s))
def fmt_size(n:int):
    if n<1024: return f"{n} B"
    if n<1048576: return f"{n/1024:.1f} KB"
    return f"{n/1048576:.1f} MB"
def clean_path(p:str):
    p=(p or "").replace("\\","/"); parts=[x for x in p.split("/") if x not in ("",".")]
    if any(x==".." for x in parts): return None
    out="/".join(parts); return out if len(out)<=200 else None
def site_url(site:dict): return f"https://{site['domain']}/" if site.get("domain") else f"{WEBHOOK_URL}/s/{site['slug']}/"
def strip_fence(t:str):
    t=t.strip(); m=re.match(r"^```[\w+-]*\n(.*?)\n?```$",t,re.S); return m.group(1) if m else t
def parse_blocks(text:str):
    text=text.strip(); parts=re.split(r"(?m)^###\s*([^\s]+)\s*$",text)
    if len(parts)==1: return {"index.html": strip_fence(text)}
    out={}
    for i in range(1,len(parts),2): out[parts[i]]=strip_fence(parts[i+1])
    return out
def looks_like_code(t:str):
    s=(t or "").strip()
    if not s or s.startswith("/"): return False
    if re.search(r"(?m)^###\s*\S+\s*$",s) or s.startswith("```"): return True
    return bool(re.search(r"<\s*(html|head|body|div|style|script)",s,re.I))

async def site_size(sid:str):
    cur = db.files.aggregate([{"$match":{"sid":sid}},{"$group":{"_id":None,"s":{"$sum":"$size"}}}])
    r = await cur.to_list(length=1)
    return r[0]["s"] if r else 0

async def put(sid:str,path:str,data:bytes,check=True):
    p=clean_path(path)
    if not p: raise ValueError(f"'{path}' invalid")
    if len(data)>MAX_FILE: raise ValueError(f"{path} too big")
    if check:
        if not await db.sites.find_one({"sid":sid},{"_id":1}): raise ValueError("Site deleted")
        old=await db.files.find_one({"sid":sid,"path":p},{"size":1})
        total=await site_size(sid)-(old["size"] if old else 0)
        if total+len(data)>MAX_SITE: raise ValueError("Site limit")
    mime=mimetypes.guess_type(p)[0] or "application/octet-stream"
    await db.files.update_one({"sid":sid,"path":p},{"$set":{"sid":sid,"path":p,"data":Binary(data),"mime":mime,"size":len(data),"ts":now()}},upsert=True)
    await db.sites.update_one({"sid":sid},{"$set":{"updated":now()}})

async def add_zip(sid:str,data:bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos=[i for i in z.infolist() if not i.is_dir()]
        if not infos: raise ValueError("ZIP empty")
        for i in infos:
            try: await put(sid,i.filename,z.read(i),check=False)
            except: pass

async def new_site(owner:int):
    sid=secrets.token_hex(6); alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        slug="".join(secrets.choice(alphabet) for _ in range(6))
        if slug not in RESERVED_SLUGS and not await db.sites.find_one({"slug":slug},{"_id":1}): break
    doc={"sid":sid,"slug":slug,"code":"EC-"+secrets.token_hex(5).upper(),"owner":owner,"title":"Untitled Site","created":now(),"updated":now(),"views":0}
    await db.sites.insert_one(doc); return doc

async def refresh_title(sid:str):
    f=await db.files.find_one({"sid":sid,"path":"index.html"}) or await db.files.find_one({"sid":sid,"path":{"$regex":r"\.html?$"}})
    if f:
        m=re.search(rb"<title[^>]*>(.*?)</title>", bytes(f["data"][:20000]), re.I|re.S)
        if m: t=m.group(1).decode("utf8","ignore").strip()[:60]; await db.sites.update_one({"sid":sid},{"$set":{"title":t}})

async def drop_site_data(sid:str): await db.files.delete_many({"sid":sid}); await db.sites.delete_one({"sid":sid})
async def delete_site(site:dict): await drop_site_data(site["sid"])
async def can_edit(uid:int,site:dict):
    if uid in ADMINS or site.get("owner")==uid: return True
    u=await db.users.find_one({"uid":uid},{"unlocked":1}); return bool(u and site["sid"] in u.get("unlocked",[]))
async def quota_ok(uid:int): return uid in ADMINS or await db.sites.count_documents({"owner":uid})<MAX_SITES
async def read_doc(bot,obj):
    buf=io.BytesIO(); await bot.download(obj,destination=buf); return buf.getvalue()

WELCOME="<b>WEB MAKER</b>"
MODE_TEXT="<b>Create Website</b>\nChoose mode"
QUICK_TEXT="<b>Quick Actions</b>"

def B(text,data=None,url=None):
    if url: return InlineKeyboardButton(text=text,url=url)
    return InlineKeyboardButton(text=text,callback_data=data)
def KB(*rows): return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])
def reply_kb(uid:int):
    rows=[[KeyboardButton(text=BTN_CREATE),KeyboardButton(text="📂 My Websites")],[KeyboardButton(text="✏️ Edit by Code"),KeyboardButton(text="❓ Help")]]
    if uid in ADMINS: rows.append([KeyboardButton(text="🛠 Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True,is_persistent=True)
def menu_kb(uid:int):
    rows=[[B("➕ Create Website","new")],[B("📂 My Websites","my")],[B("❓ Help","help")]]
    if uid in ADMINS: rows.append([B("🛠 Admin Panel","adm")])
    return KB(*rows)
def mode_kb(): return KB([B("📝 Paste Code","m:paste")],[B("📄 Single File / ZIP","m:single")],[B("📦 Multiple Files","m:multi")],[B("⬅️ Menu","menu")])
cancel_kb=KB([B("✖️ Cancel","cancel")])
def done_kb(sid:str): return KB([B("✅ Done",f"done:{sid}"),B("✖️ Cancel","cancel")])
async def card(site:dict):
    n=await db.files.count_documents({"sid":site["sid"]}); size=await site_size(site["sid"])
    return f"🌐 <b>{esc(site['title'])}</b>\n{esc(site_url(site))}\nCode <code>{site['code']}</code>\n{n} files · {fmt_size(size)}"
def panel_kb(site:dict):
    sid=site["sid"]; rows=[]
    if site_url(site).startswith("https://"): rows.append([B("🌍 Open Website",url=site_url(site))])
    rows+=[[B("📝 Paste Code",f"pe:{sid}"),B("📤 Upload Files",f"up:{sid}")],[B("📁 Files",f"fl:{sid}"),B("🔗 Short Link",f"sl:{sid}")],[B("🗑 Delete",f"del:{sid}"),B("⬅️ My Sites","my")]]
    return KB(*rows)

_PAGE="<!doctype html><html><head><meta charset=utf-8></head><body><h1>%(code)s</h1><h2>%(title)s</h2><p>%(msg)s</p></body></html>"
def page(status,code,title,msg): return web.Response(text=_PAGE % {"code":code,"title":title,"msg":msg}, status=status, content_type="text/html")
def not_found(): return page(404,"404","Not found")
async def serve_site(site:dict,tail:str,is_dir:bool):
    p=clean_path(tail)
    if p is None: return not_found()
    cands=[p,p+".html",p+"/index.html"] if p else ["index.html","index.htm"]
    if p: cands.insert(0,p)
    f=None
    for c in cands:
        f=await db.files.find_one({"sid":site["sid"],"path":c})
        if f: break
    if not f and not p: f=await db.files.find_one({"sid":site["sid"]})
    if not f: return not_found()
    if not p: asyncio.create_task(db.sites.update_one({"sid":site["sid"]},{"$inc":{"views":1}}))
    return web.Response(body=bytes(f["data"]), content_type=f.get("mime") or "text/html")

def _req_host(r): return r.host.split(":")[0].lower()
async def _site_by_host(h):
    s=await db.sites.find_one({"domain":h})
    if not s and h.startswith("www."): s=await db.sites.find_one({"domain":h[4:]})
    return s
async def h_health(r): return web.json_response({"ok":True})
async def h_site_redirect(r):
    q=f"?{r.query_string}" if r.query_string else ""
    raise web.HTTPFound(f"/s/{r.match_info['slug']}/{q}")
async def h_site(r):
    site=await db.sites.find_one({"slug":r.match_info["slug"].lower()})
    if not site: return not_found()
    return await serve_site(site, r.match_info["tail"], r.path.endswith("/"))
async def h_root(r):
    host=_req_host(r); tail=r.match_info["tail"]
    if host not in LOCAL_HOSTS:
        site=await _site_by_host(host)
        if site: return await serve_site(site, tail, r.path.endswith("/"))
        return page(404,"404","Domain not connected")
    if tail=="": return page(200,"🌐","Web Maker")
    return not_found()

@web.middleware
async def web_error_middleware(request, handler):
    try: return await handler(request)
    except web.HTTPException: raise
    except Exception as e:
        import traceback
        log.exception("web error on %s", request.path)
        tb = traceback.format_exc()[-2000:]
        return web.Response(text=f"500 Error\n{tb}", status=500, content_type="text/plain")

def add_routes(app):
    app.router.add_get("/health", h_health)
    app.router.add_get("/s/{slug}", h_site_redirect)
    app.router.add_get("/s/{slug}/{tail:.*}", h_site)
    app.router.add_get("/{tail:.*}", h_root)

r=Router()
class S(StatesGroup):
    paste_new=State(); single_new=State(); multi=State(); edit_code=State(); slug=State()
def plain_text(m: Message): return bool(m.text) and not m.text.startswith("/")

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
        try: await ev.message.edit_text(text,reply_markup=kb)
        except: await ev.message.answer(text,reply_markup=kb)
    else: await ev.answer(text,reply_markup=kb)

async def reset(state:FSMContext):
    d=await state.get_data()
    if d.get("fresh") and d.get("sid") and not await db.files.count_documents({"sid":d["sid"]}): await db.sites.delete_one({"sid":d["sid"]})
    await state.clear()
async def send_card(ev,site,banner=""): await show(ev,banner+await card(site),panel_kb(site))
async def finish_new(ev,site):
    await refresh_title(site["sid"]); site=await db.sites.find_one({"sid":site["sid"]})
    await send_card(ev,site,banner="✨ Live!\n\n")
async def auth(c:CallbackQuery,sid:str):
    site=await db.sites.find_one({"sid":sid})
    if not site: await c.answer("Gone",show_alert=True); return None
    if not await can_edit(c.from_user.id,site): await c.answer("No access",show_alert=True); return None
    return site

@r.message(CommandStart())
async def cmd_start(m:Message,state:FSMContext):
    await reset(state); await m.answer(WELCOME, reply_markup=reply_kb(m.from_user.id)); await m.answer(QUICK_TEXT, reply_markup=menu_kb(m.from_user.id))
@r.message(Command("new"))
@r.message(F.text==BTN_CREATE)
@r.callback_query(F.data=="new")
async def cmd_new(ev,state:FSMContext):
    if isinstance(ev, Message): await reset(state); await ev.answer(MODE_TEXT, reply_markup=mode_kb())
    else: await show(ev,MODE_TEXT,mode_kb())
@r.callback_query(F.data=="menu")
async def cb_menu(c:CallbackQuery,state:FSMContext):
    await reset(state); await show(c,QUICK_TEXT,menu_kb(c.from_user.id))
@r.message(Command("mysites"))
@r.message(F.text==BTN_MY)
@r.callback_query(F.data=="my")
async def my_sites(ev,state:FSMContext):
    await reset(state); uid=ev.from_user.id
    u=await db.users.find_one({"uid":uid},{"unlocked":1}) or {}
    q={"$or":[{"owner":uid},{"sid":{"$in":u.get("unlocked",[])}}]}
    items=await db.sites.find(q).sort("updated",-1).to_list(30)
    rows=[[B(f"🌐 {s['title'][:24]} · /{s['slug']}",f"s:{s['sid']}")] for s in items]
    rows.append([B("➕ New","new"),B("⬅️ Menu","menu")])
    text=f"My Websites ({len(items)})" if items else "No websites"
    await show(ev,text,KB(*rows))
@r.callback_query(F.data.startswith("m:"))
async def cb_mode(c:CallbackQuery,state:FSMContext):
    if not await quota_ok(c.from_user.id): return await c.answer(f"Limit {MAX_SITES}",show_alert=True)
    mode=c.data.split(":")[1]
    if mode=="paste":
        await state.set_state(S.paste_new); await show(c,"📝 Send HTML code",cancel_kb)
    elif mode=="single":
        await state.set_state(S.single_new); await show(c,"📄 Send file/ZIP as File",cancel_kb)
    else:
        site=await new_site(c.from_user.id); await state.set_state(S.multi); await state.update_data(sid=site["sid"],fresh=True)
        await show(c,"📦 Send files as File, press Done",done_kb(site["sid"]))
@r.message(StateFilter(S.paste_new, S.single_new, None), F.text)
async def create_from_text(m:Message,state:FSMContext):
    if not m.text or m.text.startswith("/"): return
    if await state.get_state() is None and not ("<" in m.text and ">" in m.text): return
    if not await quota_ok(m.from_user.id): return await m.answer("Limit reached")
    site=await new_site(m.from_user.id)
    try:
        for name,content in parse_blocks(m.text).items(): await put(site["sid"],name,content.encode("utf-8"))
    except Exception as e:
        await drop_site_data(site["sid"]); return await m.answer(f"Failed {e}", reply_markup=cancel_kb)
    await state.clear(); await finish_new(m,site)
@r.message(F.document)
async def create_from_doc(m:Message,state:FSMContext,bot:Bot):
    uid=m.from_user.id; name=m.document.file_name or "file"
    sd=await state.get_data(); sid=sd.get("sid")
    if not sid:
        if not await quota_ok(uid): return await m.answer("Limit")
        site=await new_site(uid); sid=site["sid"]; await state.update_data(sid=sid,fresh=True)
    else: site=await db.sites.find_one({"sid":sid})
    if not site: return
    buf=io.BytesIO(); await bot.download(m.document,destination=buf); data=buf.getvalue()
    if name.lower().endswith(".zip"): await add_zip(sid,data)
    else: await put(sid,name,data)
    await m.reply("Saved", reply_markup=KB([B("Manage",f"s:{sid}")]))
    if sd.get("fresh") and await db.files.count_documents({"sid":sid})>=1:
        await state.clear(); site=await db.sites.find_one({"sid":sid}); await finish_new(m,site)
@r.callback_query(F.data.startswith("done:"))
async def cb_done(c:CallbackQuery,state:FSMContext):
    sid=c.data.split(":")[1]; site=await db.sites.find_one({"sid":sid})
    if not site: return await c.answer("Gone",show_alert=True)
    await state.clear(); await refresh_title(sid); site=await db.sites.find_one({"sid":sid}); await send_card(c,site,banner="✨ Live!\n\n")
@r.callback_query(F.data.startswith("s:"))
async def cb_site(c:CallbackQuery,state:FSMContext):
    await reset(state); site=await auth(c,c.data.split(":")[1])
    if site: await send_card(c,site)
@r.callback_query(F.data.startswith("fl:"))
async def cb_fl(c:CallbackQuery):
    site=await auth(c,c.data.split(":")[1])
    if site:
        items=await db.files.find({"sid":site["sid"]}).to_list(200)
        txt="\n".join([f"{i['path']} {fmt_size(i['size'])}" for i in items]) or "No files"
        await show(c,txt,KB([B("Back",f"s:{site['sid']}")]))
@r.callback_query(F.data.startswith("del:"))
async def cb_del(c:CallbackQuery):
    site=await auth(c,c.data.split(":")[1])
    if site: await show(c,f"Delete {esc(site['title'])}?",KB([B("Yes",f"delok:{site['sid']}"),B("No",f"s:{site['sid']}")]))
@r.callback_query(F.data.startswith("delok:"))
async def cb_delok(c:CallbackQuery):
    site=await auth(c,c.data.split(":")[1])
    if site: await delete_site(site); await show(c,"Deleted",KB([B("My Sites","my")]))
@r.callback_query()
async def stale_callback(c:CallbackQuery): await c.answer("Expired",show_alert=True)

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
import asyncio, html as _html, io, logging, mimetypes, re, secrets, time, zipfile
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatAction
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

log = logging.getLogger("webify")

def now():
    return int(time.time())
def esc(s):
    return _html.escape(str(s))
def fmt_size(n:int):
    if n < 1024: return f"{n} B"
    if n < 1048576: return f"{n/1024:.1f} KB"
    return f"{n/1048576:.1f} MB"
def clean_path(p:str):
    p = (p or "").replace("\\","/")
    parts = [x for x in p.split("/") if x not in ("",".")]
    if any(x==".." for x in parts): return None
    out = "/".join(parts)
    return out if len(out) <= 200 else None
def site_url(site:dict):
    if site.get("domain"): return f"https://{site['domain']}/"
    return f"{WEBHOOK_URL}/s/{site['slug']}/"
def strip_fence(t:str):
    t = t.strip()
    m = re.match(r"^```[\w+-]*\n(.*?)\n?```$", t, re.S)
    return m.group(1) if m else t
def parse_blocks(text:str):
    text = text.strip()
    parts = re.split(r"(?m)^###\s*([^\s]+)\s*$", text)
    if len(parts) == 1: return {"index.html": strip_fence(text)}
    out = {}
    for i in range(1, len(parts), 2): out[parts[i]] = strip_fence(parts[i+1])
    return out
def looks_like_code(t:str):
    s = (t or "").strip()
    if not s or s.startswith("/"): return False
    if re.search(r"(?m)^###\s*\S+\s*$", s) or s.startswith("```"): return True
    return bool(re.search(r"<\s*(html|head|body|div)", s, re.I))

async def site_size(sid:str):
    cur = db.files.aggregate([{"$match":{"sid":sid}},{"$group":{"_id":None,"s":{"$sum":"$size"}}}])
    r = await cur.to_list(length=1)
    return r[0]["s"] if r else 0
async def save_file(sid:str, path:str, data:bytes, need_space:bool=True):
    p = clean_path(path)
    if not p: raise ValueError("invalid path")
    if len(data) > MAX_FILE: raise ValueError("file too big")
    if need_space:
        if not await db.sites.find_one({"sid":sid},{"_id":1}): raise ValueError("Site deleted")
        old = await db.files.find_one({"sid":sid,"path":p},{"size":1})
        total = await site_size(sid) - (old["size"] if old else 0)
        if total + len(data) > MAX_SITE: raise ValueError("storage full")
    mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
    await db.files.update_one({"sid":sid,"path":p},{"$set":{"sid":sid,"path":p,"data":Binary(data),"mime":mime,"size":len(data),"ts":now()}}, upsert=True)
    await db.sites.update_one({"sid":sid},{"$set":{"updated":now()}})
async def add_zip(sid:str, data:bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX")]
        if not infos: raise ValueError("ZIP empty")
        prefix = ""; names = [i.filename for i in infos]
        firsts = {n.split("/")[0] for n in names if "/" in n}
        if len(firsts)==1 and all("/" in n for n in names): prefix = list(firsts)[0] + "/"
        cnt = 0
        for i in infos:
            name = i.filename[len(prefix):] if prefix and i.filename.startswith(prefix) else i.filename
            if not name.strip(): continue
            try: await save_file(sid, name, z.read(i), need_space=False); cnt += 1
            except: pass
        return cnt
async def new_site(owner:int):
    sid = secrets.token_hex(6); alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        slug = "".join(secrets.choice(alphabet) for _ in range(6))
        if slug not in RESERVED_SLUGS and not await db.sites.find_one({"slug":slug},{"_id":1}): break
    doc = {"sid":sid,"slug":slug,"code":"EC-"+secrets.token_hex(5).upper(),"owner":owner,"title":"Untitled - Webify Bot","created":now(),"updated":now(),"views":0}
    await db.sites.insert_one(doc); return doc
async def refresh_title(sid:str):
    f = await db.files.find_one({"sid":sid,"path":"index.html"}) or await db.files.find_one({"sid":sid,"path":{"$regex":r"\.html?$"}})
    if f:
        m = re.search(rb"<title[^>]*>(.*?)</title>", bytes(f["data"][:20000]), re.I|re.S)
        if m:
            t = m.group(1).decode("utf8","ignore").strip()[:60]
            if t: await db.sites.update_one({"sid":sid},{"$set":{"title":t}})
async def drop_site_data(sid:str): await db.files.delete_many({"sid":sid}); await db.sites.delete_one({"sid":sid})
async def delete_site(site:dict): await drop_site_data(site["sid"])
async def can_edit(uid:int, site:dict):
    if uid in ADMINS or site.get("owner")==uid: return True
    u = await db.users.find_one({"uid":uid},{"unlocked":1}); return bool(u and site["sid"] in u.get("unlocked",[]))
async def quota_ok(uid:int): return uid in ADMINS or await db.sites.count_documents({"owner":uid}) < MAX_SITES
async def read_doc(bot, obj):
    buf = io.BytesIO(); await bot.download(obj, destination=buf); return buf.getvalue()

WELCOME = "<b>Webify Bot - Premium</b>\nInstant Hosting"
HELP_TEXT = "<b>Webify Help</b>\n/new - Create\n/mysites - Manage"
MODE_TEXT = "<b>Create New Site</b>"

def B(text, data=None, url=None):
    if url: return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=data)
def KB(*rows): return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])
def reply_kb(uid:int):
    rows = [[KeyboardButton(text="Create Website"),KeyboardButton(text="My Websites")],[KeyboardButton(text="Edit by Code"),KeyboardButton(text="Help")]]
    if uid in ADMINS: rows.append([KeyboardButton(text="Admin")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)
def menu_kb(uid:int):
    rows = [[B("Create Website - Premium","new")],[B("My Sites","my"),B("Edit Code","editcode")],[B("Help & Guide","help")]]
    if uid in ADMINS: rows.append([B("Admin Panel","adm")])
    return KB(*rows)
def mode_kb(): return KB([B("Paste Code - Fast","m:paste")],[B("Single File / ZIP","m:single")],[B("Multi Files - Pro","m:multi")],[B("Back to Menu","menu")])
cancel_kb = KB([B("Cancel","cancel")])
def done_kb(sid:str): return KB([B("Deploy Now","done:"+sid),B("Cancel","cancel")])
async def premium_card(site:dict):
    n = await db.files.count_documents({"sid":site["sid"]}); size = await site_size(site["sid"]); link = site_url(site)
    return f"<b>{esc(site['title'])}</b>\nLink: {esc(link)}\nCode: <code>{site['code']}</code>\nFiles: {n} - {fmt_size(size)}\n"
def panel_kb(site:dict):
    sid = site["sid"]
    return KB([B("Open Live Site", url=site_url(site))],[B("Files Manager","fl:"+sid), B("Short Link","sl:"+sid)],[B("Show Code","code:"+sid), B("Delete Site","del:"+sid)],[B("My Sites","my")])
def page(status, code, title, msg, extra=""):
    html = "<html><body><h1>" + esc(code) + "</h1><h2>" + esc(title) + "</h2><p>" + esc(msg) + "</p>" + extra + "</body></html>"
    return web.Response(text=html, status=status, content_type="text/html")
def not_found():
    return page(404, "Not Found", "Not Found", "Site not found")

async def serve_site(site:dict, tail:str, is_dir:bool):
    p = clean_path(tail)
    if p is None:
        return not_found()
    if not p:
        cands = ["index.html","index.htm"]
    elif is_dir:
        cands = [p+"/index.html", p+"/index.htm"]
    else:
        cands = [p, p+".html", p+"/index.html"]
    f = None
    for c in cands:
        f = await db.files.find_one({"sid":site["sid"],"path":c})
        if f:
            break
    if not f and not p:
        f = await db.files.find_one({"sid":site["sid"],"path":{"$regex":r"\.html?$"}}) or await db.files.find_one({"sid":site["sid"]})
    if not f:
        e = await db.files.find_one({"sid":site["sid"],"path":"404.html"})
        if e:
            return web.Response(body=bytes(e["data"]), status=404, content_type="text/html")
        return not_found()
    if not p:
        async def _inc_view():
            try:
                await db.sites.update_one({"sid":site["sid"]}, {"$inc":{"views":1}})
            except:
                pass
        asyncio.create_task(_inc_view())
    mime = f.get("mime") or "application/octet-stream"
    headers = {"Cache-Control":"public, max-age=60"}
    return web.Response(body=bytes(f["data"]), content_type=mime, headers=headers)

def _req_host(r): return r.host.split(":")[0].lower()
async def _site_by_host(h):
    s = await db.sites.find_one({"domain":h})
    if not s and h.startswith("www."): s = await db.sites.find_one({"domain":h[4:]})
    return s
async def h_health(r): return web.json_response({"ok":True, "bot":"Webify Bot"})
async def h_site_redirect(r):
    q = f"?{r.query_string}" if r.query_string else ""
    raise web.HTTPFound(f"/s/{r.match_info['slug']}/{q}")
async def h_site(r):
    site = await db.sites.find_one({"slug":r.match_info["slug"].lower()})
    if not site: return not_found()
    return await serve_site(site, r.match_info["tail"], r.path.endswith("/"))
async def h_root(r):
    host = _req_host(r); tail = r.match_info["tail"]
    if host not in LOCAL_HOSTS:
        site = await _site_by_host(host)
        if site: return await serve_site(site, tail, r.path.endswith("/"))
        return page(404, "Domain", "Domain not connected", "Add domain")
    if tail == "": return page(200, "Webify", "Webify Bot", "Telegram bot")
    return not_found()

@web.middleware
async def web_error_middleware(request, handler):
    try: return await handler(request)
    except web.HTTPException: raise
    except Exception as e:
        ref = secrets.token_hex(3); log.exception("web error %s", ref)
        if request.path == "/webhook": return web.Response(status=200, text="ok")
        return page(500, "Error", "Error", "Ref " + ref)

def add_routes(app):
    app.router.add_get("/health", h_health)
    app.router.add_get("/s/{slug}", h_site_redirect)
    app.router.add_get("/s/{slug}/{tail:.*}", h_site)
    app.router.add_get("/{tail:.*}", h_root)

r = Router(); ALBUMS = {}; ALBUM_LOCK = asyncio.Lock()
class S(StatesGroup):
    paste_new = State(); single_new = State(); multi = State(); edit_code = State(); slug = State()
def plain_text(m: Message): return bool(m.text) and not m.text.startswith("/")

class Guard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u and not u.is_bot:
            await db.users.update_one({"uid":u.id},{"$set":{"name":u.full_name,"username":u.username,"last":now()}, "$setOnInsert":{"joined":now(),"banned":False,"unlocked":[]}}, upsert=True)
            if u.id not in ADMINS:
                d = await db.users.find_one({"uid":u.id},{"banned":1})
                if d and d.get("banned"): return
        return await handler(event, data)

async def show(ev, text, kb=None):
    if isinstance(ev, CallbackQuery):
        try: await ev.answer()
        except: pass
        msg = ev.message
        if not isinstance(msg, Message): return await ev.bot.send_message(ev.from_user.id, text, reply_markup=kb)
        try: await msg.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower(): return
            await msg.answer(text, reply_markup=kb)
    else: await ev.answer(text, reply_markup=kb)

async def reset(state:FSMContext):
    d = await state.get_data()
    if d.get("fresh") and d.get("sid") and not await db.files.count_documents({"sid":d["sid"]}):
        await db.sites.delete_one({"sid":d["sid"]})
    await state.clear()
async def send_card(ev, site, banner=""):
    txt = banner + await premium_card(site); await show(ev, txt, panel_kb(site))
async def finish_new(ev, site):
    await refresh_title(site["sid"]); site = await db.sites.find_one({"sid":site["sid"]}); await send_card(ev, site, banner="Deployed!\n")
async def auth(c:CallbackQuery, sid:str):
    site = await db.sites.find_one({"sid":sid})
    if not site: await c.answer("Site deleted", show_alert=True); return None
    if not await can_edit(c.from_user.id, site): await c.answer("No access", show_alert=True); return None
    return site
@r.message(CommandStart())
async def cmd_start(m:Message, state:FSMContext):
    await reset(state)
    await m.answer(WELCOME, reply_markup=reply_kb(m.from_user.id))
    await m.answer("Menu", reply_markup=menu_kb(m.from_user.id))

@r.message(Command("help"))
async def cmd_help(m:Message, state:FSMContext):
    await reset(state)
    await m.answer(HELP_TEXT, reply_markup=KB([B("Menu","menu")]))

@r.callback_query(F.data=="help")
async def cb_help(c:CallbackQuery):
    await show(c, HELP_TEXT, KB([B("Menu","menu")]))

@r.callback_query(F.data=="menu")
async def cb_menu(c:CallbackQuery, state:FSMContext):
    await reset(state)
    await show(c, "Menu", menu_kb(c.from_user.id))

@r.message(Command("cancel"))
@r.callback_query(F.data=="cancel")
async def cancel(ev, state:FSMContext):
    await reset(state)
    await show(ev, "Cancelled", menu_kb(ev.from_user.id))

@r.message(Command("new"))
async def cmd_new(m:Message, state:FSMContext):
    await reset(state)
    await m.answer(MODE_TEXT, reply_markup=mode_kb())

@r.callback_query(F.data=="new")
async def cb_new(c:CallbackQuery, state:FSMContext):
    await reset(state)
    await show(c, MODE_TEXT, mode_kb())

@r.message(Command("mysites"))
@r.callback_query(F.data=="my")
async def my_sites(ev, state:FSMContext):
    await reset(state)
    uid = ev.from_user.id
    u = await db.users.find_one({"uid":uid},{"unlocked":1}) or {}
    q = {"$or":[{"owner":uid},{"sid":{"$in":u.get("unlocked",[])}}]}
    items = await db.sites.find(q).sort("updated",-1).to_list(30)
    if not items:
        return await show(ev, "No sites yet", KB([B("Create First Site","new"),B("Menu","menu")]))
    rows = [[B(f"{s['title'][:26]} - /{s['slug']}",f"s:{s['sid']}")] for s in items]
    rows.append([B("New Site","new"),B("Menu","menu")])
    await show(ev, f"Your Sites ({len(items)}/{MAX_SITES})", KB(*rows))

@r.callback_query(F.data=="editcode")
async def ask_code(ev, state:FSMContext):
    await reset(state)
    await state.set_state(S.edit_code)
    await show(ev, "Enter Edit Code like EC-XXXXX", cancel_kb)

async def try_code(m:Message, state:FSMContext, code:str):
    site = await db.sites.find_one({"code":code.strip().upper()})
    if not site:
        return await m.answer("Invalid code", reply_markup=cancel_kb)
    await db.users.update_one({"uid":m.from_user.id},{"$addToSet":{"unlocked":site["sid"]}})
    await state.clear()
    await send_card(m, site, banner="Access Granted\n")

@r.message(StateFilter(S.edit_code), plain_text)
async def edit_code_in(m:Message, state:FSMContext):
    await try_code(m, state, m.text)

@r.message(Command("edit"))
async def cmd_edit(m:Message, command:CommandObject, state:FSMContext):
    await reset(state)
    if command.args:
        return await try_code(m, state, command.args)
    await ask_code(m, state)

@r.callback_query(F.data.startswith("m:"))
async def cb_mode(c:CallbackQuery, state:FSMContext):
    if not await quota_ok(c.from_user.id):
        return await c.answer("Limit reached", show_alert=True)
    mode = c.data.split(":")[1]
    if mode == "paste":
        await state.set_state(S.paste_new)
        await show(c, "Paste Mode - Send HTML now", cancel_kb)
    elif mode == "single":
        await state.set_state(S.single_new)
        await show(c, "Single Upload - Send file or ZIP", cancel_kb)
    else:
        site = await new_site(c.from_user.id)
        await state.set_state(S.multi)
        await state.update_data(sid=site["sid"], fresh=True)
        await show(c, "Pro Builder - Send files then Done", done_kb(site["sid"]))

@r.message(StateFilter(S.paste_new, S.single_new, None), plain_text)
async def create_from_text(m:Message, state:FSMContext):
    cur = await state.get_state()
    if cur is None and not looks_like_code(m.text):
        return await m.answer("Send code?", reply_markup=menu_kb(m.from_user.id))
    if not await quota_ok(m.from_user.id):
        return await m.answer("Limit reached")
    site = await new_site(m.from_user.id)
    try:
        for name, content in parse_blocks(m.text).items():
            await save_file(site["sid"], name, content.encode("utf-8"))
    except Exception as e:
        await drop_site_data(site["sid"])
        return await m.answer(f"Deploy Failed {esc(str(e))}", reply_markup=cancel_kb)
    await state.clear()
    await finish_new(m, site)

@r.message(StateFilter(S.paste_new, S.single_new, None), F.document)
@r.message(StateFilter(S.multi), F.document)
async def create_from_doc(m:Message, state:FSMContext, bot:Bot):
    uid = m.from_user.id
    d = m.document
    name = d.file_name or "index.html"
    gid = m.media_group_id
    async with ALBUM_LOCK:
        if gid and gid in ALBUMS:
            sid = ALBUMS[gid][0]
            site = await db.sites.find_one({"sid":sid})
        else:
            sd = await state.get_data()
            sid = sd.get("sid")
            if sid:
                site = await db.sites.find_one({"sid":sid})
            else:
                if not await quota_ok(uid):
                    return await m.answer("Limit")
                site = await new_site(uid)
                sid = site["sid"]
                await state.update_data(sid=sid, fresh=True)
                if gid:
                    ALBUMS[gid] = (sid, time.time())
    if not site:
        return
    try:
        data = await read_doc(bot, d)
        if name.lower().endswith(".zip"):
            await add_zip(sid, data)
        else:
            fname = "index.html" if name.lower().endswith((".html",".htm")) else name
            await save_file(sid, fname, data)
    except Exception as e:
        if not await db.files.count_documents({"sid":sid}):
            await drop_site_data(sid)
        return await m.answer(f"Upload Failed {esc(str(e))}", reply_markup=cancel_kb)
    sd = await state.get_data()
    if sd.get("fresh") and sd.get("sid")==sid:
        if await state.get_state()==S.multi:
            await m.reply(f"Saved {esc(name)}", reply_markup=done_kb(sid))
        else:
            await state.clear()
            await finish_new(m, site)
    else:
        await m.reply(f"Saved {esc(name)}", reply_markup=KB([B("Manage Site", f"s:{sid}")]))

@r.callback_query(F.data.startswith("done:"))
async def cb_done(c:CallbackQuery, state:FSMContext):
    sid = c.data.split(":")[1]
    d = await state.get_data()
    site = await db.sites.find_one({"sid":sid})
    if not site:
        return await c.answer("Gone", show_alert=True)
    if not await db.files.count_documents({"sid":sid}):
        if d.get("fresh"):
            await db.sites.delete_one({"sid":sid})
            await state.clear()
            return await show(c, "No files sent", menu_kb(c.from_user.id))
        return await c.answer("No files", show_alert=True)
    await state.clear()
    await refresh_title(sid)
    site = await db.sites.find_one({"sid":sid})
    await send_card(c, site, banner="Deployed!\n")

@r.callback_query(F.data.startswith("s:"))
async def cb_site(c:CallbackQuery, state:FSMContext):
    await reset(state)
    site = await auth(c, c.data.split(":")[1])
    if site:
        await send_card(c, site)

@r.callback_query(F.data.startswith("fl:"))
async def cb_fl(c:CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if site:
        items = await db.files.find({"sid":site["sid"]}).sort("path",1).to_list(200)
        txt = "\n".join([f"{esc(i['path'])} - {fmt_size(i['size'])}" for i in items]) or "No files"
        await show(c, f"Files - {esc(site['title'])}\n" + txt, KB([B("Back",f"s:{site['sid']}")]))

@r.callback_query(F.data.startswith("sl:"))
async def cb_sl(c:CallbackQuery, state:FSMContext):
    site = await auth(c, c.data.split(":")[1])
    if not site:
        return
    await state.set_state(S.slug)
    await state.update_data(sid=site["sid"])
    await show(c, f"Short Link Current: /s/{site['slug']}/ Send new slug", cancel_kb)

@r.message(StateFilter(S.slug), plain_text)
async def slug_in(m:Message, state:FSMContext):
    sid = (await state.get_data())["sid"]
    slug = m.text.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}[a-z0-9]", slug) or slug in RESERVED_SLUGS:
        return await m.answer("Invalid slug", reply_markup=cancel_kb)
    if await db.sites.find_one({"slug":slug,"sid":{"$ne":sid}}):
        return await m.answer("Slug taken", reply_markup=cancel_kb)
    await db.sites.update_one({"sid":sid},{"$set":{"slug":slug,"updated":now()}})
    await state.clear()
    await send_card(m, await db.sites.find_one({"sid":sid}), banner="Link Updated\n")

@r.callback_query(F.data.startswith("del:"))
async def cb_del(c:CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if site:
        await show(c, f"Delete {esc(site['title'])}?", KB([B("Yes Delete","delok:"+site['sid']),B("No Keep","s:"+site['sid'])]))

@r.callback_query(F.data.startswith("delok:"))
async def cb_delok(c:CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if site:
        await delete_site(site)
        await show(c, "Deleted", KB([B("My Sites","my"),B("Menu","menu")]))

@r.callback_query(F.data.startswith("code:"))
async def cb_code(c:CallbackQuery):
    site = await auth(c, c.data.split(":")[1])
    if site:
        await c.message.answer(f"Code <code>{site['code']}</code>")
        await c.answer()

@r.callback_query()
async def stale_callback(c:CallbackQuery):
    await c.answer("Button expired /start", show_alert=True)

async def create_app():
    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(Guard())
    dp.callback_query.middleware(Guard())
    dp.include_router(r)
    app = web.Application(middlewares=[web_error_middleware])
    add_routes(app)
    wh = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
    wh.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)
    return app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
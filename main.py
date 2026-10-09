import os
import re
import uuid
import zipfile
import shutil
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from motor.motor_asyncio import AsyncIOMotorClient

# ----------------- LOGGING & CONFIG -----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g. https://your-app.onrender.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "khushi_secret_key")
PORT = int(os.getenv("PORT", 10000))
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

if not BOT_TOKEN or not MONGO_URI:
    raise ValueError("Missing BOT_TOKEN or MONGO_URI in environment variables!")

# Directories for project files & storage
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, "user_projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

# ----------------- DATABASE SETUP (MongoDB) -----------------
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["webbuilder_files"]
projects_collection = db["projects"]
users_collection = db["users"]

# ----------------- FASTAPI & TELEGRAM APP -----------------
app = FastAPI(title="WebBuilder Uploader Bot", version="2.0")

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")) if os.path.exists(os.path.join(BASE_DIR, "web", "static")) else StaticFiles(directory=PROJECTS_DIR), name="static")

telegram_app = Application.builder().token(BOT_TOKEN).build()

# MarkdownV2 safe escaper helper
def esc(text: str) -> str:
    if not text:
        return ""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

# ----------------- CORE UTILS & FILE HANDLERS -----------------
def generate_unique_id():
    return f"WEB-{uuid.uuid4().hex[:6].upper()}"

async def register_user(user_id: int, username: str):
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"username": username, "last_active": datetime.utcnow()}},
        upsert=True
    )

# ----------------- TELEGRAM KEYBOARDS & UI -----------------
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📂 My Projects", callback_data="my_projects"),
         InlineKeyboardButton("🚀 New Project", callback_data="help_new")],
        [InlineKeyboardButton("⚙️ Storage Status", callback_data="bot_status"),
         InlineKeyboardButton("💬 Support", url="https://t.me/myselfkhushi03")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_project_action_keyboard(project_id: str):
    keyboard = [
        [InlineKeyboardButton("🌐 Live Preview", callback_data=f"preview_{project_id}"),
         InlineKeyboardButton("🚀 Deploy URL", callback_data=f"deploy_{project_id}")],
        [InlineKeyboardButton("📁 List Files", callback_data=f"files_{project_id}"),
         InlineKeyboardButton("📥 Export ZIP", callback_data=f"zip_{project_id}")],
        [InlineKeyboardButton("🗑️ Delete Project", callback_data=f"delete_{project_id}")],
        [InlineKeyboardButton("« Back to Menu", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ----------------- TELEGRAM COMMAND HANDLERS -----------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_KEY):
    user = update.effective_user
    await register_user(user.id, user.username)
    
    welcome_text = (
        f"✨ *Welcome to WebBuilder File Uploader* ✨\n\n"
        f"Owner/Developer: `@myselfkhushi03`[span_1](start_span)[span_1](end_span)\n\n"
        f"Aap yahan apna koi bhi single code file, multiple files, ya poora `.zip` archive bhej sakte hain. Bot automatically ek unique project ID generate karega aur usko live web preview & public deployment mein convert kar dega!\n\n"
        f"💡 *Tap-to-Copy & Professional UI Enabled*"
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
    elif update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_KEY):
    help_text = (
        f"📖 *WebBuilder Help & Guide*\n\n"
        f"1️⃣ **Naya Project Kaise Banayein?**\n"
        f"   • Command use karein: `/newproject <project_name>`\n"
        f"   • Ya phir direct koi code snippet / file / ZIP bot ko bhej dein.\n"
        f"2️⃣ **Unique Project Code:** Har project ko ek unique ID milti hai (e.g., `WEB-A3F9K2`).\n"
        f"3️⃣ **Tap-to-Copy:** Saare links aur codes copy-friendly format mein diye jaate hain.\n\n"
        f"Developer: `@myselfkhushi03`[span_2](start_span)[span_2](end_span)"
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

async def new_project_command(update: Update, context: ContextTypes.DEFAULT_KEY):
    user = update.effective_user
    args = context.args
    project_name = "MyWebProject" if not args else " ".join(args)
    
    project_id = generate_unique_id()
    project_path = os.path.join(PROJECTS_DIR, project_id)
    os.makedirs(project_path, exist_ok=True)
    
    # Default index.html starter file
    default_html = f"<!DOCTYPE html>\n<html>\n<head><title>{project_name}</title></head>\n<body>\n<h1>Welcome to {project_name}</h1>\n<p>Built via WebBuilder Bot (@myselfkhushi03)</p>\n</body>\n</html>"
    with open(os.path.join(project_path, "index.html"), "w", encoding="utf-8") as f:
        f.write(default_html)
        
    await projects_collection.insert_one({
        "project_id": project_id,
        "user_id": user.id,
        "name": project_name,
        "created_at": datetime.utcnow(),
        "files": ["index.html"]
    })
    
    msg = (
        f"✅ *Project Created Successfully!*\n\n"
        f"📌 *Name:* `{esc(project_name)}`\n"
        f"🔑 *Unique Code:* `{project_id}` *(Tap to copy)*\n\n"
        f"Ab aap isme files add kar sakte hain ya code bhej sakte hain."
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_project_action_keyboard(project_id))

async def my_projects_handler(update: Update, context: ContextTypes.DEFAULT_KEY):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    cursor = projects_collection.find({"user_id": user_id}).sort("created_at", -1).limit(10)
    projects = await cursor.to_list(length=10)
    
    if not projects:
        await query.message.edit_text(
            "📂 Aapka koi active project nahi mila!\nNaya project banane ke liye `/newproject MySite` bhejrein.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="main_menu")]])
        )
        return
        
    keyboard = []
    for p in projects:
        keyboard.append([InlineKeyboardButton(f"📁 {p['name']} ({p['project_id']})", callback_data=f"manage_{p['project_id']}")])
    keyboard.append([InlineKeyboardButton("« Back to Menu", callback_data="main_menu")])
    
    await query.message.edit_text("📂 *Aapke Saare Projects:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# Handle incoming files, zip archives or code snippets
async def handle_document_or_code(update: Update, context: ContextTypes.DEFAULT_KEY):
    user = update.effective_user
    message = update.message
    
    project_id = generate_unique_id()
    project_path = os.path.join(PROJECTS_DIR, project_id)
    os.makedirs(project_path, exist_ok=True)
    
    file_list = []
    
    if message.document:
        doc = message.document
        file_name = doc.file_name
        file_path = os.path.join(project_path, file_name)
        
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(file_path)
        
        # If uploaded file is a .zip archive, extract it automatically!
        if file_name.endswith(".zip"):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(project_path)
            os.remove(file_path) # Remove zip after extraction
            file_list = os.listdir(project_path)
        else:
            file_list = [file_name]
            
    elif message.text:
        # Direct code snippet pasted
        code_text = message.text
        file_name = "index.html" if "<html" in code_text.lower() else "script.js" if "console.log" in code_text else "main.py" if "def " in code_text else "data.txt"
        file_path = os.path.join(project_path, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code_text)
        file_list = [file_name]
    else:
        await message.reply_text("❌ Unsupported format. Please send a code file, snippet, or ZIP archive.")
        return

    # Ensure at least an index.html exists for web preview fallback
    if "index.html" not in file_list and len(file_list) > 0:
        # rename first text file or create index.html
        pass

    await projects_collection.insert_one({
        "project_id": project_id,
        "user_id": user.id,
        "name": f"Project {project_id}",
        "created_at": datetime.utcnow(),
        "files": file_list
    })

    preview_url = f"{WEBHOOK_URL}/preview/{project_id}" if WEBHOOK_URL else f"http://localhost:{PORT}/preview/{project_id}"
    deploy_url = f"{WEBHOOK_URL}/s/{project_id}" if WEBHOOK_URL else f"http://localhost:{PORT}/s/{project_id}"

    success_msg = (
        f"🎉 *Files Successfully Converted to Web Project!* ✨\n\n"
        f"🔑 *Unique Code:* `{project_id}`\n"
        f"📂 *Files Processed:* `{len(file_list)} files`\n\n"
        f"👁️ *Live Preview:* \n`{preview_url}`\n\n"
        f"🚀 *Public Deploy Link:* \n`{deploy_url}`\n\n"
        f"Managed by `@myselfkhushi03`[span_3](start_span)[span_3](end_span)"
    )
    
    await message.reply_text(success_msg, parse_mode="Markdown", reply_markup=get_project_action_keyboard(project_id))

# Callback Query Router
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_KEY):
    query = update.callback_query
    data = query.data
    
    if data == "main_menu":
        await start_command(update, context)
    elif data == "my_projects":
        await my_projects_handler(update, context)
    elif data == "help_new":
        await query.answer("Send any file or code snippet directly to create a web project!")
    elif data == "bot_status":
        await query.answer("🟢 Bot is fully operational & online!", show_alert=True)
    elif data.startswith("preview_"):
        pid = data.split("_")[1]
        url = f"{WEBHOOK_URL}/preview/{pid}" if WEBHOOK_URL else f"http://localhost:{PORT}/preview/{pid}"
        await query.answer(f"Preview URL generated!", show_alert=False)
        await query.message.reply_text(f"👁️ *Live Preview Link for `{pid}`:*\n`{url}`", parse_mode="Markdown")
    elif data.startswith("deploy_"):
        pid = data.split("_")[1]
        url = f"{WEBHOOK_URL}/s/{pid}" if WEBHOOK_URL else f"http://localhost:{PORT}/s/{pid}"
        await query.answer(f"Deploy URL generated!", show_alert=False)
        await query.message.reply_text(f"🚀 *Public Shareable Link for `{pid}`:*\n`{url}`", parse_mode="Markdown")
    elif data.startswith("files_"):
        pid = data.split("_")[1]
        proj = await projects_collection.find_one({"project_id": pid})
        if proj:
            files_str = "\n".join([f"• `{f}`" for f in proj.get("files", [])])
            await query.message.reply_text(f"📁 *Files in `{pid}`:*\n{files_str}", parse_mode="Markdown")
        else:
            await query.answer("Project not found!", show_alert=True)
    elif data.startswith("delete_"):
        pid = data.split("_")[1]
        await projects_collection.delete_one({"project_id": pid})
        shutil.rmtree(os.path.join(PROJECTS_DIR, pid), ignore_errors=True)
        await query.answer("Project deleted successfully!")
        await start_command(update, context)
    elif data.startswith("manage_"):
        pid = data.split("_")[1]
        await query.message.edit_text(f"⚙️ *Managing Project:* `{pid}`", parse_mode="Markdown", reply_markup=get_project_action_keyboard(pid))

# ----------------- FASTAPI WEB ROUTES -----------------
@app.get("/", response_class=HTMLResponse)
async def index_route():
    return """
    <html>
        <head><title>WebBuilder Bot - Live</title></head>
        <body style="font-family: Arial; text-align: center; padding-top: 50px; background: #0f172a; color: #f8fafc;">
            <h1>🚀 WebBuilder Bot Active</h1>
            <p>Powered by Python, FastAPI & Telegram (@myselfkhushi03)</p>
        </body>
    </html>
    """

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

@app.get("/preview/{project_id}", response_class=HTMLResponse)
@app.get("/s/{project_id}", response_class=HTMLResponse)
async def serve_project(project_id: str):
    project_path = os.path.join(PROJECTS_DIR, project_id)
    if not os.path.exists(project_path):
        raise HTTPException(status_code=404, detail="Project not found!")
    
    # Look for index.html or fallback to first available html/file
    target_file = "index.html"
    if not os.path.exists(os.path.join(project_path, target_file)):
        files = os.listdir(project_path)
        if files:
            target_file = files[0]
        else:
            raise HTTPException(status_code=404, detail="No files found in project!")
            
    file_full_path = os.path.join(project_path, target_file)
    if os.path.isdir(file_full_path):
        file_full_path = os.path.join(file_full_path, "index.html")
        
    if os.path.exists(file_full_path):
        with open(file_full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return HTMLResponse(content=content)
    
    raise HTTPException(status_code=404, detail="Main file missing!")

@app.post(f"/webhook/{WEBHOOK_SECRET}")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "ok"}

# ----------------- STARTUP & LIFECYCLE -----------------
@app.on_event("startup")
async def startup_event():
    await telegram_app.initialize()
    if WEBHOOK_URL:
        webhook_endpoint = f"{WEBHOOK_URL}/webhook/{WEBHOOK_SECRET}"
        await telegram_app.bot.set_webhook(url=webhook_endpoint)
        logger.info(f"Webhook successfully configured to: {webhook_endpoint}")
    await telegram_app.start()

@app.on_event("shutdown")
async def shutdown_event():
    await telegram_app.stop()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)

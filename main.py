import os, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import requests

# --- BAS YAHAN TOKEN DAAL DE ---
BOT_TOKEN = "8959965012:AAHIe7Kr8-uEHjsOK9S4SHjm0fCnl31HIBM"

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "Live"

def run_flask():
    app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

async def start(update, context):
    await update.message.reply_text("Chikuu online hai babu 😘")

async def chat(update, context):
    await update.message.reply_text(f"Tune bola: {update.message.text} ❤️")

def main():
    threading.Thread(target=run_flask).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.run_polling()

if __name__ == "__main__":
    main()

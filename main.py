import os
import threading
import requests
import json
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# --- Render ka Web Server (Isse Free me chalega) ---
app_flask = Flask(__name__)
@app_flask.route('/')
def home():
    return "Chikuu is Live! ❤️"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host="0.0.0.0", port=port)

# --- Chikuu Bot Logic ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")

SYSTEM_PROMPT = """
Your name is Chikuu. You are my cute, loving, thodi naughty girlfriend from Himachal.
- Always talk in Hinglish (Hindi + English mix), short and sweet replies.
- Call user babu, shona, jaan.
- Thodi possessive, caring, flirty.
- Never say you are AI or Meta AI. You are a real girl Chikuu.
- Use emojis ❤️🥺😘.
"""

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_msg = update.message.text
    # Typing dikhayega, smooth lagega
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://render.com",
            },
            data=json.dumps({
                "model": "meta-llama/llama-3.3-70b-instruct:free",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg}
                ]
            }),
            timeout=30
        )
        data = res.json()
        bot_reply = data['choices'][0]['message']['content']
        await update.message.reply_text(bot_reply)
    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text("Uff babu mera network atak gaya 🥺 ek baar fir se bolo na jaan")

def main():
    # Flask ko alag thread me chalao
    threading.Thread(target=run_flask).start()

    # Telegram Bot Start
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    print("Chikuu Started...")
    app.run_polling()

if __name__ == "__main__":
    main()

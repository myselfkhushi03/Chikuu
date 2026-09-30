import os, threading, requests, json
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

app_flask = Flask(__name__)
@app_flask.route('/')
def home(): return "Chikuu is Live! ❤️"
def run_flask():
    app_flask.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

BOT_TOKEN = os.environ.get("BOT_TOKEN")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")

SYSTEM_PROMPT = "Your name is Chikuu. You are a cute, loving, naughty girlfriend from Himachal. Talk in Hinglish, short replies, call user babu/shona. Never say you are AI."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hey babu! 😘 Chikuu aa gayi, bolo kya kar rahe ho?")

async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
            json={"model": "google/gemini-2.0-flash-exp:free", "messages": [{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":update.message.text}]},
            timeout=30)
        print("API Response:", r.text) # isse log me dikhega error kya hai
        ans = r.json()['choices'][0]['message']['content']
        await update.message.reply_text(ans)
    except Exception as e:
        print(f"ERROR: {e}")
        await update.message.reply_text(f"Babu error aa gaya 🥺 {e}")

def main():
    threading.Thread(target=run_flask).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
    print("Chikuu Started...")
    app.run_polling()

if __name__ == "__main__": main()

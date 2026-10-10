# ✨ Webify Bot — Telegram Edition

GenZ aesthetic website builder bot. Deploy on Render in 5 min.

## 🎯 Features

- 💻 **Code Mode** — HTML/CSS/JS paste → website ready
- 📁 **Files Mode** — multiple files ya `.zip` bhej → inline ho jaata hai
- 📝 **Details Mode** — guided 5-step flow (title → tagline → color → layout → notes)
- 📦 **Downloads** — ZIP + Single inlined HTML dono
- 🗄️ **MongoDB** — sessions, users, global stats
- ⚡ **Webhook mode** — Render-ready
- 🐛 **Zero silent errors** — har exception user + logs me visible

## 📂 Structure

```
webify-bot/
├── bot.py                  # Entry point
├── config.py               # Env vars
├── logger.py               # Logging
├── database.py             # MongoDB wrapper
├── keyboards.py            # Inline keyboards
├── templates.py            # HTML template builder
├── utils.py                # Helpers
├── handlers/
│   ├── start.py            # /start /help /status /stats /reset /cancel
│   ├── code_mode.py        # 💻
│   ├── files_mode.py       # 📁 + /done
│   ├── details_mode.py     # 📝
│   └── callbacks.py        # Callback router
├── requirements.txt
├── Procfile
├── render.yaml
├── runtime.txt
├── .env.example
├── .gitignore
└── README.md
```

## 🚀 Render Deploy

### 1. GitHub push

```bash
git init
git add .
git commit -m "webify bot"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

### 2. Render setup

- New → **Web Service**
- Repo connect
- Runtime: **Python 3**
- Build: `pip install -r requirements.txt`
- Start: `python bot.py`
- Plan: **Free**

### 3. Environment Variables

| Key | Value | Example |
|-----|-------|---------|
| `BOT_TOKEN` | @BotFather se | `123456:ABC-xyz` |
| `ADMIN_ID` | Tera Telegram ID | `123456789` |
| `MONGO_URL` | MongoDB Atlas URI | `mongodb+srv://...` |
| `WEBHOOK_URL` | Render URL | `https://webify-bot.onrender.com` |
| `WEBHOOK_SECRET` | Random string | `xyz-abc-123-secret` |
| `PORT` | `1000` (Render default) | `1000` |
| `PYTHON_VERSION` | `3.11.9` | `3.11.9` |
| `DB_NAME` | optional | `webify_bot` |
| `LOG_LEVEL` | optional | `INFO` |

### 4. Deploy → wait 2 min → bot live 🎉

## 🤖 Commands

| Command | Kya karta hai |
|---------|--------------|
| `/start` | Main menu |
| `/help` | Guide |
| `/status` | Current session |
| `/stats` | Global stats |
| `/done` | Files mode complete |
| `/reset` | Session clear |
| `/cancel` | Cancel flow |

## 🐛 Debugging

Agar bot reply na kare:

1. **Logs check kare** Render dashboard → Logs tab
2. **Webhook status** — browser me khol:
   ```
   https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo
   ```
3. **Mongo connect** — Render logs me `MongoDB connected` dikhna chahiye
4. **Port mismatch** — Render automatically `PORT` inject karta hai, hardcode mat kar

Har module alag hai — bug aaye toh seedha file pakad me.

## 📝 Notes

- Font: `Playfair Display italic` (Daily Bonus aesthetic) har generated site me
- Session TTL: 24h (MongoDB TTL index)
- Free tier: 15 min inactivity → sleep → first message pe 30-60s wake time
- Keep-alive ke liye UptimeRobot se `/` ping karwa le

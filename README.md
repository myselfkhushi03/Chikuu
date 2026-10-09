# Web Maker Bot

Telegram bot that turns pasted code, single files, multiple files or ZIPs into live websites.
Runs on a Render **Web Service** in webhook mode and hosts the sites itself (files stored in MongoDB).

## Render setup

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `python bot.py`
- **Environment variables**

| Variable | Value |
|---|---|
| `BOT_TOKEN` | token from @BotFather |
| `WEBHOOK_URL` | `https://<your-service>.onrender.com` (no trailing slash) |
| `WEBHOOK_SECRET` | random string, only `A-Z a-z 0-9 _ -` |
| `MONGO_URL` | MongoDB connection string |
| `PORT` | `1000` |
| `ADMIN_ID` | your Telegram user id (comma separate for more admins) |

Optional: `DB_NAME` (webmaker), `MAX_SITES` (15 per user), `MAX_FILE_MB` (15), `MAX_SITE_MB` (60),
`RENDER_API_KEY` + `RENDER_SERVICE_ID` (auto-add custom domains on Render).

Also set `PYTHON_VERSION=3.11.9` on Render.

## Features

- Create by pasting code (use `### filename` separators for several files), single file, multiple files, or ZIP
- Every site gets a short link `/s/<slug>/` and a unique edit code `EC-XXXXXXXXXX`
- Edit by code from any account: replace code, upload/replace files, delete files, change short link, regenerate code, delete site
- Custom domains: send the domain in the bot, point `CNAME` to your Render host
- Admin: `/admin`, `/stats`, `/users`, `/sites`, `/site slug`, `/delsite slug`, `/ban id`, `/unban id`, `/broadcast`

## Notes

- Free Render services sleep. Ping `https://<service>.onrender.com/health` every 5 min (UptimeRobot) to keep it awake.
- You host user content: monitor `/sites` and delete or ban abusers (phishing, malware).

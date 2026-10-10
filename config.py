"""
⚙️ Config — saare env vars yahin.
Agar koi var missing ho, startup pe clear error milega.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, required: bool = True, default: str = "") -> str:
    val = os.environ.get(key, default).strip()
    if required and not val:
        raise RuntimeError(f"❌ ENV VAR MISSING: '{key}' — Render dashboard me add kar bhai!")
    return val


# ---------- REQUIRED ----------
BOT_TOKEN       = _get("BOT_TOKEN")
ADMIN_ID        = int(_get("ADMIN_ID", default="0") or "0")
MONGO_URL       = _get("MONGO_URL")
WEBHOOK_URL     = _get("WEBHOOK_URL")          # ex: https://myapp.onrender.com
WEBHOOK_SECRET  = _get("WEBHOOK_SECRET")       # random string (URL-safe)
PORT            = int(_get("PORT", default="1000") or "1000")

# ---------- OPTIONAL ----------
PYTHON_VERSION  = os.environ.get("PYTHON_VERSION", "3.11.9")
DB_NAME         = os.environ.get("DB_NAME", "webify_bot")
LOG_LEVEL       = os.environ.get("LOG_LEVEL", "INFO")

# ---------- DERIVED ----------
WEBHOOK_PATH    = f"/webhook/{WEBHOOK_SECRET}"
WEBHOOK_FULL    = f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}"

# ---------- CONSTANTS ----------
MAX_FILE_SIZE       = 20 * 1024 * 1024   # 20 MB per file
MAX_FILES_PER_USER  = 50
SESSION_TTL_HOURS   = 24

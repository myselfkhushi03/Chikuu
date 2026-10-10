"""
⚙️ Config — saare env vars yahin.
dotenv optional hai — Render pe env vars directly milte hain.
"""
import os

# dotenv sirf local dev ke liye (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get(key: str, required: bool = True, default: str = "") -> str:
    val = (os.environ.get(key) or default).strip()
    if required and not val:
        raise RuntimeError(f"❌ ENV VAR MISSING: '{key}' — Render dashboard me add kar bhai!")
    return val


# ---------- REQUIRED ----------
BOT_TOKEN       = _get("BOT_TOKEN")
ADMIN_ID        = int(_get("ADMIN_ID", required=False, default="0") or "0")
MONGO_URL       = _get("MONGO_URL")
WEBHOOK_URL     = _get("WEBHOOK_URL")
WEBHOOK_SECRET  = _get("WEBHOOK_SECRET")
PORT            = int(_get("PORT", required=False, default="1000") or "1000")

# ---------- OPTIONAL ----------
PYTHON_VERSION  = os.environ.get("PYTHON_VERSION", "3.11.9")
DB_NAME         = os.environ.get("DB_NAME", "webify_bot")
LOG_LEVEL       = os.environ.get("LOG_LEVEL", "INFO")

# ---------- DERIVED ----------
WEBHOOK_PATH    = f"/webhook/{WEBHOOK_SECRET}"
WEBHOOK_FULL    = f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}"

# ---------- CONSTANTS ----------
MAX_FILE_SIZE       = 20 * 1024 * 1024
MAX_FILES_PER_USER  = 50
SESSION_TTL_HOURS   = 24

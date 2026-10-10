import os, re
from urllib.parse import urlparse

def _env(n, d=""): return os.getenv(n, d).strip()
def _num(n, d, cast=int):
    try: return cast(_env(n, str(d)))
    except: raise SystemExit(f"Env {n} must be number")

BOT_TOKEN = _env("BOT_TOKEN")
WEBHOOK_URL = _env("WEBHOOK_URL").rstrip("/")
WEBHOOK_SECRET = _env("WEBHOOK_SECRET")
MONGO_URL = _env("MONGO_URL")
if not WEBHOOK_URL.startswith("https://"): WEBHOOK_URL = "https://" + WEBHOOK_URL
PORT = _num("PORT", 10000)
ADMINS = {int(x) for x in re.findall(r"-?\d+", _env("ADMIN_ID"))}
DB_NAME = _env("DB_NAME", "webmaker")
MAX_SITES = _num("MAX_SITES", 15)
MAX_FILE = int(_num("MAX_FILE_MB", 15, float) * 1024 * 1024)
MAX_SITE = int(_num("MAX_SITE_MB", 60, float) * 1024 * 1024)
RENDER_API_KEY = _env("RENDER_API_KEY")
RENDER_SERVICE_ID = _env("RENDER_SERVICE_ID")
BASE_HOST = urlparse(WEBHOOK_URL).hostname or "localhost"
RESERVED_SLUGS = {"admin", "api", "s", "health", "webhook", "static", "www"}
import os, re
from urllib.parse import urlparse

def _env(n, d=""): return os.getenv(n, d).strip()
def _num(n, d, cast=int):
    try: return cast(_env(n, str(d)) or d)
    except: return d

BOT_TOKEN = _env("BOT_TOKEN")
WEBHOOK_URL = _env("WEBHOOK_URL").rstrip("/")
WEBHOOK_SECRET = _env("WEBHOOK_SECRET")
MONGO_URL = _env("MONGO_URL")

if WEBHOOK_URL and not WEBHOOK_URL.startswith("https://"):
    WEBHOOK_URL = "https://" + WEBHOOK_URL

PORT = _num("PORT", 10000)
ADMINS = {int(x) for x in re.findall(r"-?\d+", _env("ADMIN_ID"))}
DB_NAME = _env("DB_NAME", "webify")
MAX_SITES = _num("MAX_SITES", 15)
MAX_FILE_MB = _num("MAX_FILE_MB", 15, float)
MAX_SITE_MB = _num("MAX_SITE_MB", 60, float)
MAX_FILE = int(MAX_FILE_MB * 1024 * 1024)
MAX_SITE = int(MAX_SITE_MB * 1024 * 1024)
RENDER_API_KEY = _env("RENDER_API_KEY")
RENDER_SERVICE_ID = _env("RENDER_SERVICE_ID")

# AUTO BASE_HOST
if _env("BASE_HOST"):
    BASE_HOST = _env("BASE_HOST").lower()
else:
    try:
        BASE_HOST = urlparse(WEBHOOK_URL).hostname or ""
    except:
        BASE_HOST = ""

LOCAL_HOSTS = {h for h in [BASE_HOST.lower(), "localhost", "127.0.0.1", f"www.{BASE_HOST.lower()}" if BASE_HOST else ""] if h}
RESERVED_SLUGS = {"admin", "api", "s", "health", "webhook", "static", "www", "login", "logout", "dashboard"}
BOT_USERNAME = _env("BOT_USERNAME", "")
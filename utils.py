import re, mimetypes, secrets, html as _html, time
from bson import Binary

# ye sab tere purane app.py se liya hai
SAFE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
BAD = {".env",".git"}

def esc(s): return _html.escape(str(s or ""), quote=False)
def now(): return int(time.time())
def fmt_size(n):
    for u in ("B","KB","MB"):
        if n < 1024: return f"{n:.0f} {u}"
        n/=1024
    return f"{n:.1f} GB"

def clean_path(p: str):
    p = (p or "").strip().replace("\\","/").lstrip("/")
    if not p or p.startswith(".") or "//" in p or ".." in p: return None
    parts=[]
    for x in p.split("/"):
        if x in ("",".", ".."): continue
        if x.lower() in BAD or not SAFE.fullmatch(x): return None
        parts.append(x)
    if not parts or len("/".join(parts)) > 180: return None
    return "/".join(parts)

def site_url(site): 
    from config import BASE_HOST, WEBHOOK_URL
    return f"{WEBHOOK_URL}/s/{site['slug']}/"
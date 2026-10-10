from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, DB_NAME
import logging
log = logging.getLogger("webmaker")

class _DB: 
    users=None
    sites=None
    files=None

db = _DB()
_client = None

async def init_db():
    global _client
    _client = AsyncIOMotorClient(MONGO_URL)
    # ping
    await _client.admin.command("ping")
    d = _client[DB_NAME]
    db.users, db.sites, db.files = d["users"], d["sites"], d["files"]
    await db.users.create_index("uid", unique=True)
    await db.sites.create_index("sid", unique=True)
    await db.sites.create_index("slug", unique=True)
    await db.sites.create_index("code", unique=True)
    log.info("MongoDB connected OK")
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL, DB_NAME
import logging
log = logging.getLogger("webmaker")

class _DB: users=sites=files=None
db = _DB()

async def init_db():
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    await client.admin.command("ping")
    d = client[DB_NAME]
    db.users, db.sites, db.files = d["users"], d["sites"], d["files"]
    await db.users.create_index("uid", unique=True)
    await db.sites.create_index("sid", unique=True)
    await db.sites.create_index("slug", unique=True)
    await db.sites.create_index("code", unique=True)
    log.info("MongoDB connected")
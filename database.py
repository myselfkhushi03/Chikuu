"""🗄️ MongoDB — users, sessions, stats."""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

from config import MONGO_URL, DB_NAME, SESSION_TTL_HOURS
from logger import log


class Database:
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.users = None
        self.sessions = None
        self.stats = None

    async def connect(self):
        try:
            self.client = AsyncIOMotorClient(
                MONGO_URL,
                serverSelectionTimeoutMS=8000,
                connectTimeoutMS=8000,
            )
            # ping
            await self.client.admin.command("ping")
            self.db = self.client[DB_NAME]
            self.users    = self.db["users"]
            self.sessions = self.db["sessions"]
            self.stats    = self.db["stats"]
            await self.users.create_index("user_id", unique=True)
            await self.sessions.create_index("user_id", unique=True)
            await self.sessions.create_index("updated_at", expireAfterSeconds=SESSION_TTL_HOURS * 3600)
            log.info("✅ MongoDB connected")
        except Exception as e:
            log.exception("❌ MongoDB connect fail")
            raise

    async def close(self):
        if self.client:
            self.client.close()
            log.info("🔌 MongoDB closed")

    # ---------- USERS ----------
    async def upsert_user(self, user_id: int, username: str = "", first_name: str = ""):
        try:
            await self.users.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "username": username,
                        "first_name": first_name,
                        "last_seen": datetime.utcnow(),
                    },
                    "$setOnInsert": {"created_at": datetime.utcnow(), "generations": 0},
                },
                upsert=True,
            )
        except Exception:
            log.exception(f"upsert_user fail uid={user_id}")

    async def inc_generations(self, user_id: int):
        try:
            await self.users.update_one(
                {"user_id": user_id},
                {"$inc": {"generations": 1}},
                upsert=True,
            )
            await self.stats.update_one(
                {"_id": "global"},
                {"$inc": {"total_generations": 1}, "$set": {"last_update": datetime.utcnow()}},
                upsert=True,
            )
        except Exception:
            log.exception(f"inc_generations fail uid={user_id}")

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        try:
            return await self.users.find_one({"user_id": user_id})
        except Exception:
            log.exception(f"get_user fail uid={user_id}")
            return None

    async def get_global_stats(self) -> Dict[str, Any]:
        try:
            doc = await self.stats.find_one({"_id": "global"})
            total_users = await self.users.count_documents({})
            return {
                "total_users": total_users,
                "total_generations": (doc or {}).get("total_generations", 0),
            }
        except Exception:
            log.exception("get_global_stats fail")
            return {"total_users": 0, "total_generations": 0}

    # ---------- SESSIONS ----------
    async def get_session(self, user_id: int) -> Dict[str, Any]:
        try:
            doc = await self.sessions.find_one({"user_id": user_id})
            if not doc:
                return {"user_id": user_id, "files": {}, "mode": None, "temp": {}}
            doc.setdefault("files", {})
            doc.setdefault("temp", {})
            doc.setdefault("mode", None)
            return doc
        except Exception:
            log.exception(f"get_session fail uid={user_id}")
            return {"user_id": user_id, "files": {}, "mode": None, "temp": {}}

    async def save_session(self, user_id: int, session: Dict[str, Any]):
        try:
            session["updated_at"] = datetime.utcnow()
            await self.sessions.update_one(
                {"user_id": user_id},
                {"$set": session},
                upsert=True,
            )
        except Exception:
            log.exception(f"save_session fail uid={user_id}")

    async def reset_session(self, user_id: int):
        try:
            await self.sessions.update_one(
                {"user_id": user_id},
                {"$set": {"files": {}, "mode": None, "temp": {}, "updated_at": datetime.utcnow()}},
                upsert=True,
            )
        except Exception:
            log.exception(f"reset_session fail uid={user_id}")


db = Database()

import json
from collections import defaultdict
from datetime import datetime

import redis.asyncio as aioredis
from sqlalchemy.orm import Session

from backend.utils.config_handler import settings
from backend.utils.logger_handler import logger

# Layer 1: how many conversation turns (user+assistant pairs) to pass to the agent.
# Messages beyond this window stay in SQLite but are not sent to the LLM.
HISTORY_WINDOW = 10  # turns → 20 messages max

# In-memory fallback used when Redis is unavailable (development only)
_memory_store: dict[str, list[dict]] = defaultdict(list)


class ConversationStore:
    """Layer 2 — session cache backed by Redis with in-memory fallback."""

    def __init__(self, redis_client: aioredis.Redis | None):
        self.redis = redis_client

    async def get_history(self, conversation_id: str) -> list[dict]:
        if self.redis is None:
            return list(_memory_store[conversation_id])
        raw = await self.redis.get(f"conv:{conversation_id}")
        return json.loads(raw) if raw else []

    async def get_window(self, conversation_id: str) -> list[dict]:
        """Return only the last HISTORY_WINDOW turns to prevent context overflow."""
        history = await self.get_history(conversation_id)
        return history[-(HISTORY_WINDOW * 2):]

    async def append_message(self, conversation_id: str, role: str, content: str):
        if self.redis is None:
            _memory_store[conversation_id].append({"role": role, "content": content})
            return
        history = await self.get_history(conversation_id)
        history.append({"role": role, "content": content})
        await self.redis.setex(
            f"conv:{conversation_id}",
            86400,
            json.dumps(history, ensure_ascii=False),
        )

    async def clear(self, conversation_id: str):
        if self.redis is None:
            _memory_store.pop(conversation_id, None)
            return
        await self.redis.delete(f"conv:{conversation_id}")


PROFILE_STALE_DAYS = 30  # facts older than this are discarded on read


class ProfileStore:
    """Layer 3 — long-term user fact store backed by SQLite.

    Facts are stored as a flat JSON dict {key: value}.
    On update, newer values overwrite older ones for the same key
    (simple last-write-wins conflict resolution).
    Facts are treated as stale after PROFILE_STALE_DAYS and dropped on read
    so outdated information (e.g. old device model) never poisons the context.
    """

    def get_profile(self, user_id: str, db: Session) -> dict:
        from backend.db.models import UserProfile
        row = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if not row:
            return {}
        age_days = (datetime.utcnow() - row.updated_at).days
        if age_days > PROFILE_STALE_DAYS:
            logger.info("profile_stale", user_id=user_id, age_days=age_days)
            return {}
        return json.loads(row.facts)

    def update_profile(self, user_id: str, new_facts: dict, db: Session) -> None:
        from backend.db.models import UserProfile
        row = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if row:
            existing = json.loads(row.facts)
            existing.update(new_facts)  # newer overwrites older
            row.facts = json.dumps(existing, ensure_ascii=False)
            row.updated_at = datetime.utcnow()
        else:
            db.add(UserProfile(
                user_id=user_id,
                facts=json.dumps(new_facts, ensure_ascii=False),
            ))
        db.commit()

    @staticmethod
    def inject(profile: dict, history: list[dict]) -> list[dict]:
        """Prepend a memory context turn so the agent knows the user's facts.

        Injected as a fake user→assistant exchange so it fits any LLM message
        format without touching the system prompt.
        """
        if not profile:
            return history
        profile_text = "；".join(f"{k}：{v}" for k, v in profile.items())
        return [
            {"role": "user",      "content": f"[记忆注入] 以下是我的已知信息：{profile_text}"},
            {"role": "assistant", "content": "好的，我已记住您的相关信息，将在本次对话中参考。"},
        ] + history


profile_store = ProfileStore()


async def get_redis() -> aioredis.Redis | None:
    """Connect to Redis; return None and log a warning if unavailable."""
    try:
        client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await client.ping()
        return client
    except Exception as e:
        logger.warning("redis_unavailable", error=str(e), fallback="in-memory store")
        return None

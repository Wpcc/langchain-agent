import json
from collections import defaultdict

import redis.asyncio as aioredis

from backend.utils.config_handler import settings
from backend.utils.logger_handler import logger

# In-memory fallback used when Redis is unavailable (development only)
_memory_store: dict[str, list[dict]] = defaultdict(list)


class ConversationStore:
    def __init__(self, redis_client: aioredis.Redis | None):
        self.redis = redis_client

    async def get_history(self, conversation_id: str) -> list[dict]:
        if self.redis is None:
            return list(_memory_store[conversation_id])
        raw = await self.redis.get(f"conv:{conversation_id}")
        return json.loads(raw) if raw else []

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

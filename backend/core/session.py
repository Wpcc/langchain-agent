import json

import redis.asyncio as aioredis

from utils.config_handler import settings


class ConversationStore:
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    async def get_history(self, conversation_id: str) -> list[dict]:
        raw = await self.redis.get(f"conv:{conversation_id}")
        return json.loads(raw) if raw else []

    async def append_message(self, conversation_id: str, role: str, content: str):
        history = await self.get_history(conversation_id)
        history.append({"role": role, "content": content})
        await self.redis.setex(
            f"conv:{conversation_id}",
            86400,
            json.dumps(history, ensure_ascii=False),
        )

    async def clear(self, conversation_id: str):
        await self.redis.delete(f"conv:{conversation_id}")


async def get_redis() -> aioredis.Redis:
    return aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

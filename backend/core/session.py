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

# When total messages exceed this threshold a background summary is triggered.
# Set slightly above the window so the summary is ready before the next drop.
_SUMMARY_THRESHOLD = HISTORY_WINDOW * 2 + 2  # 22 messages
_SUMMARY_KEY = "conv_summary:{}"         # Redis key template
_SUMMARY_CURSOR_KEY = "conv_summary_cursor:{}"  # how many messages the summary covers

# In-memory fallback used when Redis is unavailable (development only)
_memory_store: dict[str, list[dict]] = defaultdict(list)
_summary_store: dict[str, str] = {}   # fallback summary store
_cursor_store: dict[str, int] = {}    # fallback cursor store


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

    async def get_window_with_summary(self, conversation_id: str) -> list[dict]:
        """Return the sliding window prefixed with a summary of dropped turns.

        If history fits within the window, returns it as-is.
        If history overflows, prepends a cached summary of the dropped turns
        so the agent retains compressed awareness of the full conversation.
        The summary is generated as a background task on first overflow and
        cached in Redis — this method never blocks on an LLM call.
        """
        history = await self.get_history(conversation_id)
        if len(history) <= HISTORY_WINDOW * 2:
            return history

        recent = history[-(HISTORY_WINDOW * 2):]
        summary = await self._get_summary(conversation_id)
        if summary:
            return [
                {"role": "user",      "content": f"[历史摘要] {summary}"},
                {"role": "assistant", "content": "好的，我已了解之前的对话背景。"},
            ] + recent
        return recent

    async def _get_summary(self, conversation_id: str) -> str:
        """Read cached summary from Redis (or in-memory fallback)."""
        key = _SUMMARY_KEY.format(conversation_id)
        if self.redis is None:
            return _summary_store.get(conversation_id, "")
        raw = await self.redis.get(key)
        return raw or ""

    async def _save_summary(self, conversation_id: str, summary: str) -> None:
        key = _SUMMARY_KEY.format(conversation_id)
        if self.redis is None:
            _summary_store[conversation_id] = summary
            return
        await self.redis.setex(key, 86400, summary)

    async def _get_cursor(self, conversation_id: str) -> int:
        """Return how many leading messages are already covered by the stored summary."""
        key = _SUMMARY_CURSOR_KEY.format(conversation_id)
        if self.redis is None:
            return _cursor_store.get(conversation_id, 0)
        raw = await self.redis.get(key)
        return int(raw) if raw else 0

    async def _save_cursor(self, conversation_id: str, cursor: int) -> None:
        key = _SUMMARY_CURSOR_KEY.format(conversation_id)
        if self.redis is None:
            _cursor_store[conversation_id] = cursor
            return
        await self.redis.setex(key, 86400, str(cursor))

    async def schedule_summary_if_needed(self, conversation_id: str, user_id: str) -> None:
        """Trigger background summarisation whenever new messages fall outside the window.

        On first overflow this summarises all dropped turns.
        On subsequent overflows it merges the existing summary with the
        newly dropped turns (those beyond the cursor) so no messages are silently lost.
        Also updates the Layer 3 episodic index with the latest summary.
        """
        import asyncio
        history = await self.get_history(conversation_id)
        if len(history) < _SUMMARY_THRESHOLD:
            return

        dropped = history[:-(HISTORY_WINDOW * 2)]
        cursor = await self._get_cursor(conversation_id)
        if len(dropped) - cursor < 2:
            return  # wait for a full turn (user+assistant) to drop before re-summarising

        newly_dropped = dropped[cursor:]
        existing_summary = await self._get_summary(conversation_id)

        async def _generate():
            from backend.core.summarizer import summarize_turns, summarize_incremental
            if existing_summary:
                summary = await summarize_incremental(existing_summary, newly_dropped)
            else:
                summary = await summarize_turns(dropped)
            if summary:
                await self._save_summary(conversation_id, summary)
                await self._save_cursor(conversation_id, len(dropped))
                # Layer 3: update episodic index so this conversation is searchable
                from backend.core.episodic_memory import episodic_store
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda: episodic_store.save(user_id, conversation_id, summary)
                )

        asyncio.create_task(_generate())

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

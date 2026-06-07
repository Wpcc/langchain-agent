"""Async background task: extract user facts from a conversation turn and
merge them into the long-term UserProfile store.

Uses lite_model (cheap, fast) so extraction never blocks the main response.
"""
import asyncio
import json

from backend.model.factory import lite_model
from backend.utils.logger_handler import logger

_EXTRACTION_PROMPT = """从下面一轮对话中提取关于用户的新事实（设备型号、使用偏好、常见问题、使用习惯等）。
规则：
1. 只提取用户明确说出的信息，不要推断或猜测。
2. 以JSON数组返回，每项格式：{{"key": "事实名", "value": "事实值"}}。
3. 无新事实则返回空数组 []。
4. 只返回JSON，不要任何其他文字。

用户：{user_msg}
助手：{assistant_msg}
"""


async def _extract_facts(user_msg: str, assistant_msg: str) -> dict:
    """Call lite_model to extract facts; return {key: value} or {} on failure."""
    try:
        prompt = _EXTRACTION_PROMPT.format(user_msg=user_msg, assistant_msg=assistant_msg)
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: lite_model.invoke(prompt).content,
        )
        facts_list = json.loads(raw.strip())
        if not isinstance(facts_list, list):
            return {}
        return {
            item["key"]: item["value"]
            for item in facts_list
            if isinstance(item, dict) and "key" in item and "value" in item
        }
    except Exception as e:
        logger.warning("profile_extraction_failed", error=str(e))
        return {}


async def generate_title_async(conversation_id: str, first_query: str, db) -> None:
    """Generate a short conversation title from the first user message."""
    from backend.db.models import Conversation

    prompt = (
        f"根据以下用户消息，生成一个10字以内的简短对话标题，只输出标题本身：\n{first_query}"
    )
    try:
        loop = asyncio.get_running_loop()
        title = await loop.run_in_executor(
            None, lambda: lite_model.invoke(prompt).content.strip()[:50]
        )
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv and title:
            conv.title = title
            db.commit()
            logger.info("title_generated", conversation_id=conversation_id, title=title)
    except Exception as e:
        logger.warning("title_generation_failed", error=str(e))


async def update_user_profile_async(user_id: str, user_msg: str, assistant_msg: str) -> None:
    """Fire-and-forget: extract facts then merge into UserProfile.

    Creates its own DB session so the WebSocket handler's session stays clean.
    """
    from backend.core.session import profile_store
    from backend.db.session import SessionLocal

    facts = await _extract_facts(user_msg, assistant_msg)
    if not facts:
        return

    db = SessionLocal()
    try:
        profile_store.update_profile(user_id, facts, db)
        logger.info("profile_updated", user_id=user_id, keys=list(facts.keys()))
    except Exception as e:
        logger.warning("profile_update_failed", user_id=user_id, error=str(e))
    finally:
        db.close()

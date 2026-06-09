"""Compress old conversation turns into a single summary string.

Called as a background task when a conversation first exceeds the sliding
window, so the summary is ready in Redis before the next request needs it.
Summarisation never blocks the WebSocket response.
"""
import asyncio

from backend.model.factory import lite_model
from backend.utils.logger_handler import logger

_PROMPT = (
    "将以下对话历史压缩为一段100字以内的简洁摘要。"
    "保留：用户的核心需求、已解决的问题、提及的设备型号或关键事实。"
    "去除：客套话、重复内容、工具调用细节。只输出摘要本身。\n\n"
    "{turns}"
)


async def summarize_turns(turns: list[dict]) -> str:
    """Summarize a list of message dicts into a compact string.

    Truncates each message to 200 chars before sending to avoid the
    summariser itself consuming a large context.
    """
    if not turns:
        return ""

    text = "\n".join(
        f"{'用户' if m['role'] == 'user' else '助手'}：{str(m['content'])[:200]}"
        for m in turns
    )
    try:
        loop = asyncio.get_running_loop()
        summary = await loop.run_in_executor(
            None,
            lambda: lite_model.invoke(_PROMPT.format(turns=text)).content.strip(),
        )
        logger.info("turns_summarized", input_turns=len(turns), summary_len=len(summary))
        return summary
    except Exception as e:
        logger.warning("summarization_failed", error=str(e))
        return ""

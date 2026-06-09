from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from backend.agent.react_agent import ReactAgent

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, get_db
from backend.core.security import decode_token
from backend.core.session import ConversationStore, get_redis, profile_store
from backend.core.profile import update_user_profile_async, generate_title_async
from backend.db.models import Conversation, Message, User
from backend.schemas.chat import ChatHistoryResponse, ConversationSchema, MessageSchema

router = APIRouter()


async def _authenticate_ws(token: str, db: Session) -> User | None:
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
    except JWTError:
        return None
    return db.query(User).filter(User.id == user_id).first()


async def _stream_agent(agent: ReactAgent, query: str, history: list) -> AsyncGenerator[str, None]:
    """Run the synchronous agent generator in a thread, yielding chunks via an async queue."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _run():
        try:
            for chunk in agent.execute_stream(query, history):
                asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
        except Exception as e:
            from backend.utils.logger_handler import logger
            logger.error("agent_stream_error", error=str(e), exc_info=True)
            asyncio.run_coroutine_threadsafe(queue.put(f"__ERROR__:{e}"), loop)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    threading.Thread(target=_run, daemon=True).start()

    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk


@router.websocket("/ws/{conversation_id}")
async def chat_websocket(
    websocket: WebSocket,
    conversation_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    await websocket.accept()

    user = await _authenticate_ws(token, db)
    if not user:
        await websocket.send_text("__ERROR__:认证失败")
        await websocket.close(code=1008)
        return

    redis_client = await get_redis()
    store = ConversationStore(redis_client)

    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        conv = Conversation(id=conversation_id, user_id=user.id)
        db.add(conv)
        db.commit()

    from backend.agent.react_agent import ReactAgent
    agent = ReactAgent(user_id=user.id)

    try:
        while True:
            query = await websocket.receive_text()

            # Layer 1: sliding window with summary of dropped turns
            history = await store.get_window_with_summary(conversation_id)

            # Stable-first ordering: inject current date as the earliest dynamic
            # message so the static system prompt prefix stays cache-friendly.
            date_str = datetime.now().strftime("%Y年%m月%d日")
            history = [
                {"role": "user",      "content": f"[系统信息] 当前日期：{date_str}"},
                {"role": "assistant", "content": "好的。"},
            ] + history

            # Layer 3: inject long-term user profile after date, before history
            user_profile = profile_store.get_profile(str(user.id), db)
            history = profile_store.inject(user_profile, history)

            full_response = ""

            async for chunk in _stream_agent(agent, query, history):
                full_response += chunk
                await websocket.send_text(chunk)

            await websocket.send_text("__END__")

            response_text = full_response.strip()
            await store.append_message(conversation_id, "user", query)
            await store.append_message(conversation_id, "assistant", response_text)

            db.add(Message(conversation_id=conversation_id, role="user", content=query))
            db.add(Message(conversation_id=conversation_id, role="assistant", content=response_text))
            db.commit()

            # Trigger background summarisation when history first overflows the window
            await store.schedule_summary_if_needed(conversation_id)

            # Layer 3: fire-and-forget profile extraction (does not block streaming)
            asyncio.create_task(
                update_user_profile_async(str(user.id), query, response_text)
            )

            # Auto-generate conversation title from the first exchange
            if conv.title == "新对话":
                asyncio.create_task(
                    generate_title_async(conversation_id, query, db)
                )

    except WebSocketDisconnect:
        pass
    finally:
        if redis_client is not None:
            await redis_client.aclose()


@router.get("/conversations", response_model=list[ConversationSchema])
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .all()
    )
    return [ConversationSchema(id=c.id, title=c.title, created_at=c.created_at) for c in convs]


@router.post("/conversations", response_model=ConversationSchema, status_code=201)
def create_conversation(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = Conversation(id=str(uuid.uuid4()), user_id=user.id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return ConversationSchema(id=conv.id, title=conv.title, created_at=conv.created_at)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise HTTPException(404, "对话不存在")
    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    db.delete(conv)
    db.commit()


@router.get("/conversations/{conversation_id}/messages", response_model=ChatHistoryResponse)
def get_messages(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()
    if not conv:
        raise HTTPException(404, "对话不存在")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id)
        .all()
    )
    return ChatHistoryResponse(
        conversation_id=conversation_id,
        messages=[MessageSchema(role=m.role, content=m.content, created_at=m.created_at) for m in messages],
    )

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from backend.agent.react_agent import ReactAgent

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user, get_db
from backend.core.security import decode_token
from backend.core.session import ConversationStore, get_redis
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
            history = await store.get_history(conversation_id)
            full_response = ""

            async for chunk in _stream_agent(agent, query, history):
                full_response += chunk
                await websocket.send_text(chunk)

            await websocket.send_text("__END__")

            await store.append_message(conversation_id, "user", query)
            await store.append_message(conversation_id, "assistant", full_response.strip())

            db.add(Message(conversation_id=conversation_id, role="user", content=query))
            db.add(Message(conversation_id=conversation_id, role="assistant", content=full_response.strip()))
            db.commit()

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

from datetime import datetime
from pydantic import BaseModel


class MessageSchema(BaseModel):
    role: str
    content: str
    created_at: datetime | None = None


class ConversationSchema(BaseModel):
    id: str
    title: str
    created_at: datetime


class ChatHistoryResponse(BaseModel):
    conversation_id: str
    messages: list[MessageSchema]

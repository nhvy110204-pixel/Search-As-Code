import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.shared.enums import MessageRole, MessageStatus


class ChatMessageBase(BaseModel):
    role: MessageRole = Field(..., description="Role của message (system, user, assistant, tool)")
    content: str = Field(..., description="Nội dung tin nhắn")


class ChatMessageCreate(ChatMessageBase):
    session_id: uuid.UUID = Field(..., description="ID của chat session")
    parent_id: Optional[uuid.UUID] = Field(None, description="ID của tin nhắn gốc (nếu là nhánh)")


class ChatMessageUpdate(BaseModel):
    status: Optional[MessageStatus] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class ChatMessageResponse(ChatMessageBase):
    id: uuid.UUID
    session_id: uuid.UUID
    parent_id: Optional[uuid.UUID]
    status: MessageStatus
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageListResponse(BaseModel):
    items: List[ChatMessageResponse]
    total: int
    page: int
    page_size: int

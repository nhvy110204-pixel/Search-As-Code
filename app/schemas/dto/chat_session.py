import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ChatSessionBase(BaseModel):
    title: Optional[str] = Field(None, max_length=255, description="Tiêu đề gợi nhớ của hội thoại")


class ChatSessionCreate(ChatSessionBase):
    user_id: uuid.UUID = Field(..., description="ID của user")
    project_id: uuid.UUID = Field(..., description="ID của project")


class ChatSessionUpdate(ChatSessionBase):
    pass


class ChatSessionResponse(ChatSessionBase):
    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionListResponse(BaseModel):
    items: List[ChatSessionResponse]
    total: int
    page: int
    page_size: int

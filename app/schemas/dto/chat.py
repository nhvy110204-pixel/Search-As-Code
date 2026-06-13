from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    session_id: uuid.UUID = Field(..., description="Existing chat session ID")
    message: str = Field(..., description="User message to stream a response for")
    parent_id: Optional[uuid.UUID] = Field(None, description="Optional parent message for branching")
    client_request_id: Optional[str] = Field(None, max_length=128, description="Client idempotency/debug identifier")

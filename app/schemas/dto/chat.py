from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    session_id: uuid.UUID = Field(..., description="Existing chat session ID")
    message: str = Field(..., description="User message to stream a response for")
    parent_id: Optional[uuid.UUID] = Field(None, description="Optional parent message for branching")
    client_request_id: Optional[str] = Field(None, max_length=128, description="Client idempotency/debug identifier")


@dataclass(frozen=True)
class PreparedChatStream:
    run_id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID
    user_message_id: uuid.UUID | None
    assistant_message_id: uuid.UUID | None
    messages: list[dict[str, str]]
    client_request_id: str | None = None
    replay_content: str | None = None
    replay_prompt_tokens: int = 0
    replay_completion_tokens: int = 0

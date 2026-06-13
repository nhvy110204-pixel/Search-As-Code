import uuid
from typing import Optional, Any, Dict, List
from app.models.chat_message import ChatMessage
from app.repositories.chat_message import ChatMessageRepository
from app.schemas.dto.chat_message import ChatMessageCreate, ChatMessageUpdate, ChatMessageListResponse
from app.services.core.base import BaseService


class ChatMessageService(BaseService[ChatMessage, ChatMessageCreate, ChatMessageUpdate]):
    def __init__(self, repository: ChatMessageRepository):
        super().__init__(repository)
        self.message_repo = repository

    def get_messages_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ChatMessageListResponse:
        return self.message_repo.list_chat_messages(page=page, page_size=page_size, filters=filters)

    def get_by_session(self, session_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[ChatMessage]:
        return self.message_repo.get_by_session(session_id, skip=skip, limit=limit)

import uuid
from typing import Optional, Any, Dict, List
from app.models.chat_message import ChatMessage
from app.repositories.chat_message import ChatMessageRepository
from app.schemas.dto.chat_message import ChatMessageCreate, ChatMessageUpdate, ChatMessageListResponse
from app.services.core.base import BaseService
from app.schemas.dto.chat_message import ChatMessageResponse
from app.core.logger import service_boundary


class ChatMessageService(BaseService[ChatMessage, ChatMessageCreate, ChatMessageUpdate]):
    def __init__(self, repository: ChatMessageRepository):
        super().__init__(repository)
        self.message_repo = repository

    @service_boundary("Get Chat Messages Paginated")
    def get_messages_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ChatMessageListResponse:
        
        messages, total = self.message_repo.list_chat_messages(page=page, page_size=page_size, filters=filters)
        message_responses = [ChatMessageResponse.model_validate(m) for m in messages]
        return ChatMessageListResponse(
            items=message_responses,
            total=total,
            page=page,
            page_size=page_size
        )

    @service_boundary("Get Chat Messages by Session")
    def get_by_session(self, session_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[ChatMessage]:
        return self.message_repo.get_by_session(session_id, skip=skip, limit=limit)

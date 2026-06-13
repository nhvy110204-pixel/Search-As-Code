import uuid
from typing import Optional, Any, Dict
from app.models.chat_session import ChatSession
from app.repositories.chat_session import ChatSessionRepository
from app.schemas.dto.chat_session import ChatSessionCreate, ChatSessionUpdate, ChatSessionListResponse
from app.services.core.base import BaseService


class ChatSessionService(BaseService[ChatSession, ChatSessionCreate, ChatSessionUpdate]):
    def __init__(self, repository: ChatSessionRepository):
        super().__init__(repository)
        self.session_repo = repository

    def get_sessions_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ChatSessionListResponse:
        return self.session_repo.list_chat_sessions(page=page, page_size=page_size, filters=filters)

    def get_by_project(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100) -> list[ChatSession]:
        return self.session_repo.get_by_project(project_id, skip=skip, limit=limit)

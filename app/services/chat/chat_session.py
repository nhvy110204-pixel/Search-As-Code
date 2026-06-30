import uuid
from typing import Optional, Any, Dict
from app.models.chat_session import ChatSession
from app.repositories.chat_session import ChatSessionRepository
from app.schemas.dto.chat_session import ChatSessionCreate, ChatSessionUpdate, ChatSessionResponse, ChatSessionListResponse
from app.services.core.base import BaseService
from app.core.logger import service_boundary


class ChatSessionService(BaseService[ChatSession, ChatSessionCreate, ChatSessionUpdate]):
    def __init__(self, repository: ChatSessionRepository):
        super().__init__(repository)
        self.session_repo = repository

    @service_boundary("Create Chat Session with User")
    def create_with_user(self, payload: ChatSessionCreate, user_id: uuid.UUID) -> ChatSession:
        """Create chat session with user_id directly."""
        create_data = payload.model_dump()
        create_data["user_id"] = user_id
        return self.repo.create(ChatSessionCreate(**create_data))

    @service_boundary("Get Chat Sessions Paginated")
    def get_sessions_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ChatSessionListResponse:
        sessions, total = self.session_repo.list_chat_sessions(page=page, page_size=page_size, filters=filters)
        session_responses = [ChatSessionResponse.model_validate(s) for s in sessions]
        return ChatSessionListResponse(
            items=session_responses,
            total=total,
            page=page,
            page_size=page_size
        )

    @service_boundary("Get Chat Sessions by Project")
    def get_by_project(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100) -> list[ChatSession]:
        return self.session_repo.get_by_project(project_id, skip=skip, limit=limit)

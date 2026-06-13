import uuid
from typing import Any, Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession
from app.repositories.base import BaseRepository
from app.schemas.dto.chat_session import ChatSessionCreate, ChatSessionListResponse, ChatSessionResponse, ChatSessionUpdate


class ChatSessionRepository(BaseRepository[ChatSession, ChatSessionCreate, ChatSessionUpdate]):
    def __init__(self, db: Session):
        super().__init__(ChatSession, db)

    def get_chat_session(self, id: uuid.UUID) -> Optional[ChatSession]:
        return self.get(id=id)

    def list_chat_sessions(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ChatSessionListResponse:
        """Phân trang chat sessions."""
        query = select(ChatSession)

        if filters:
            if "project_id" in filters and filters["project_id"] is not None:
                query = query.filter(ChatSession.project_id == filters["project_id"])
            if "user_id" in filters and filters["user_id"] is not None:
                query = query.filter(ChatSession.user_id == filters["user_id"])

        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.execute(count_query).scalar() or 0

        query = query.order_by(ChatSession.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = self.db.execute(query).scalars().all()

        session_responses = [ChatSessionResponse.model_validate(s) for s in results]

        return ChatSessionListResponse(
            items=session_responses,
            total=total,
            page=page,
            page_size=page_size
        )

    def get_by_project(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100) -> list[ChatSession]:
        """Lấy danh sách chat sessions theo project."""
        return self.get_multi(filters={"project_id": project_id}, skip=skip, limit=limit)

import uuid
from typing import Any, Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.repositories.base import BaseRepository
from app.schemas.dto.chat_message import ChatMessageCreate, ChatMessageUpdate


class ChatMessageRepository(BaseRepository[ChatMessage, ChatMessageCreate, ChatMessageUpdate]):
    def __init__(self, db: Session):
        super().__init__(ChatMessage, db)

    def get_chat_message(self, id: uuid.UUID) -> Optional[ChatMessage]:
        return self.get(id=id)

    def list_chat_messages(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> tuple[list[ChatMessage], int]:
        """Paginate chat messages. Returns (messages, total)."""
        query = select(ChatMessage)

        if filters:
            if "session_id" in filters and filters["session_id"] is not None:
                query = query.filter(ChatMessage.session_id == filters["session_id"])
            if "role" in filters and filters["role"] is not None:
                query = query.filter(ChatMessage.role == filters["role"])

        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.execute(count_query).scalar() or 0

        query = query.order_by(ChatMessage.created_at.asc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = self.db.execute(query).scalars().all()

        return list(results), total

    def get_by_session(self, session_id: uuid.UUID, skip: int = 0, limit: int = 100) -> list[ChatMessage]:
        """Lấy danh sách messages theo session."""
        return self.get_multi(filters={"session_id": session_id}, skip=skip, limit=limit, order_by=[("created_at", "asc")])

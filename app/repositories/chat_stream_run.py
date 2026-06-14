from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chat_stream_run import ChatStreamRun
from app.repositories.base import BaseRepository
from app.shared.enums import ChatStreamStatus


class ChatStreamRunRepository(BaseRepository[ChatStreamRun, None, None]):

    def __init__(self, db: Session):
        super().__init__(ChatStreamRun, db)

    def get_by_user_and_client_request_id(
        self,
        user_id: UUID,
        client_request_id: str,
    ) -> Optional[ChatStreamRun]:
        stmt = select(ChatStreamRun).where(
            ChatStreamRun.user_id == user_id,
            ChatStreamRun.client_request_id == client_request_id,
            ChatStreamRun.is_deleted == False,
        )
        return self.db.execute(stmt).scalars().first()

    def count_user_runs(
        self,
        user_id: UUID,
        created_after: Optional[datetime] = None,
        statuses: Optional[set[ChatStreamStatus]] = None,
    ) -> int:
        stmt = select(func.count()).select_from(ChatStreamRun).where(
            ChatStreamRun.user_id == user_id,
            ChatStreamRun.is_deleted == False,
        )
        if created_after is not None:
            stmt = stmt.where(ChatStreamRun.created_at >= created_after)
        if statuses:
            stmt = stmt.where(ChatStreamRun.status.in_([status.value for status in statuses]))
        return self.db.execute(stmt).scalar() or 0

    def get_with_messages(self, run_id: UUID) -> Optional[ChatStreamRun]:
        stmt = select(ChatStreamRun).where(
            ChatStreamRun.id == run_id,
            ChatStreamRun.is_deleted == False,
        )
        return self.db.execute(stmt).scalars().first()

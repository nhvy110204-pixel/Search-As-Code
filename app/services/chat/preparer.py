from typing import Any
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
import uuid

from app.config.settings import settings
from app.core.unit_of_work import UnitOfWork
from app.models.chat_message import ChatMessage
from app.schemas.dto.chat import PreparedChatStream
from app.schemas.dto.chat_message import ChatMessageCreate
from app.services.chat.constants import SYSTEM_PROMPT
from app.services.core.redis_service import redis_cache_service
from app.shared.enums import MessageRole, MessageStatus


class ChatStreamPreparer:

    def __init__(self, db: Session):
        self.db = db

    def prepare_messages(
        self,
        session_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        content: str,
        user_id: uuid.UUID,
    ) -> tuple[ChatMessage, ChatMessage]:
        with UnitOfWork(self.db) as uow:
            chat_session = uow.chat_sessions.get(session_id)
            if not chat_session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chat session not found"
                )
            if chat_session.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Chat session does not belong to user"
                )

            if parent_id:
                parent = uow.chat_messages.get(parent_id)
                if not parent or parent.session_id != session_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Parent message is invalid"
                    )

            user_message = uow.chat_messages.create(
                ChatMessageCreate(
                    session_id=session_id,
                    parent_id=parent_id,
                    role=MessageRole.USER,
                    content=content,
                )
            )
            uow.chat_messages.update(user_message, {"status": MessageStatus.COMPLETED})

            assistant_message = uow.chat_messages.create(
                ChatMessageCreate(
                    session_id=session_id,
                    parent_id=user_message.id,
                    role=MessageRole.ASSISTANT,
                    content="",
                )
            )
            uow.chat_messages.update(assistant_message, {"status": MessageStatus.STREAMING})

            redis_cache_service.invalidate_history(session_id)

            return user_message, assistant_message

    def build_provider_messages(
        self,
        session_id: uuid.UUID,
        current_message: str,
    ) -> list[dict[str, str]]:
        history = self._load_recent_history(session_id)
        messages = [{"role": MessageRole.SYSTEM.value, "content": SYSTEM_PROMPT}]
        budget_used = len(SYSTEM_PROMPT) + len(current_message)
        selected_history: list[ChatMessage] = []

        for message in history:
            if message.role in {MessageRole.USER, MessageRole.ASSISTANT, MessageRole.SYSTEM, MessageRole.TOOL}:
                next_size = len(message.content or "")
                if budget_used + next_size > settings.CHAT_HISTORY_MAX_CHARS:
                    continue
                budget_used += next_size
                selected_history.append(message)

        for message in selected_history:
            messages.append({"role": message.role.value, "content": message.content})
        messages.append({"role": MessageRole.USER.value, "content": current_message})
        return messages

    def _load_recent_history(self, session_id: uuid.UUID) -> list[Any]:
        cached = redis_cache_service.get_cached_history(session_id)
        if cached is not None:
            return cached

        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.is_deleted == False,
                ChatMessage.status == MessageStatus.COMPLETED,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(settings.CHAT_HISTORY_LIMIT)
        )
        messages = self.db.execute(stmt).scalars().all()
        history = list(reversed(messages))

        redis_cache_service.set_cached_history(session_id, history)

        return history

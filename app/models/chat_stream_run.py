from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.enums import ChatStreamStatus
from .base import AIEntityMixin, Base

if TYPE_CHECKING:
    from .chat_message import ChatMessage
    from .chat_session import ChatSession
    from .user import User


class ChatStreamRun(AIEntityMixin, Base):
    __tablename__ = "chat_stream_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    client_request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    user_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    assistant_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)

    status: Mapped[ChatStreamStatus] = mapped_column(
        String(30),
        default=ChatStreamStatus.STARTED,
        server_default=text("'started'"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    time_to_first_delta_ms: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)

    user: Mapped["User"] = relationship("User")
    session: Mapped["ChatSession"] = relationship("ChatSession")
    user_message: Mapped[Optional["ChatMessage"]] = relationship("ChatMessage", foreign_keys=[user_message_id])
    assistant_message: Mapped[Optional["ChatMessage"]] = relationship("ChatMessage", foreign_keys=[assistant_message_id])

    __table_args__ = (
        Index("idx_chat_stream_runs_user_created", "user_id", "created_at"),
        Index("idx_chat_stream_runs_user_status_created", "user_id", "status", "created_at"),
        Index(
            "uq_chat_stream_runs_user_client_request",
            "user_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL AND is_deleted = false"),
        ),
    )

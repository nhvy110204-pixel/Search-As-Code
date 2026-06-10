from __future__ import annotations

import uuid
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import ForeignKey, Text, String, Integer, Enum, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, AIEntityMixin
from app.shared.enums import MessageRole, MessageStatus

if TYPE_CHECKING:
    from .chat_session import ChatSession
    from .message_feedback import MessageFeedback


class ChatMessage(AIEntityMixin, Base):
    """Quản lý nhật ký hội thoại chi tiết. Hỗ trợ cơ chế Streaming an toàn và rẽ nhánh (Branching)."""
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    
    # Cơ chế rẽ nhánh (Branching): Khi user ấn 'Regenerate' hoặc sửa tin nhắn cũ, tin nhắn mới sẽ có parent_id trỏ về tin nhắn cũ
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MessageStatus] = mapped_column(String(20), default=MessageStatus.PENDING, server_default=text("'pending'"), nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")
    parent: Mapped[Optional["ChatMessage"]] = relationship("ChatMessage", remote_side="ChatMessage.id")
    feedback: Mapped[Optional["MessageFeedback"]] = relationship("MessageFeedback", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_messages_session_render", "session_id", "created_at", postgresql_where=text("is_deleted = false")),
    )
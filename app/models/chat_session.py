from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, AIEntityMixin

if TYPE_CHECKING:
    from .chat_message import ChatMessage
    from .session_input import SessionInput
    from .project import Project
    from .user import User

class ChatSession(AIEntityMixin, Base):
    """Phiên hội thoại Chatbot theo phạm vi một Project, không bám vào một document đơn lẻ."""
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Tiêu đề gợi nhớ của hội thoại")

    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    project: Mapped["Project"] = relationship("Project", back_populates="chat_sessions")
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )
    inputs: Mapped[List["SessionInput"]] = relationship(
        "SessionInput",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionInput.created_at",
    )

    __table_args__ = (
        Index("idx_chat_sessions_project_user", "project_id", "user_id"),
    )
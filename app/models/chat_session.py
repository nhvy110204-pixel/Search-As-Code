from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, AIEntityMixin

if TYPE_CHECKING:
    from .chat_message import ChatMessage
    from .document import Document
    from .user import User

class ChatSession(AIEntityMixin, Base):
    """Phiên hội thoại Chatbot. Nếu dính vào document_id thì chỉ chat chuyên sâu với tài liệu đó (Project RAG)."""
    __tablename__ = "chat_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), 
        nullable=True, 
        index=True
    )
    
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Tiêu đề gợi nhớ của hội thoại")

    user: Mapped["User"] = relationship("User", back_populates="chat_sessions")
    document: Mapped[Optional["Document"]] = relationship("Document", back_populates="chat_sessions")
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )
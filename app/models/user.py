from __future__ import annotations

from typing import List, TYPE_CHECKING
from sqlalchemy import String, Boolean, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, AIEntityMixin

if TYPE_CHECKING:
    from .api_key import APIKey
    from .chat_session import ChatSession
    from .document import Document
    from .project import Project
    from .message_feedback import MessageFeedback
    from .session_input import SessionInput
    from .sac_task import SACTask

class User(AIEntityMixin, Base):
    """Quản lý thông tin tài khoản người dùng chính trong hệ thống."""
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
    encrypted_custom_api_keys: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    api_keys: Mapped[List["APIKey"]] = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    chat_sessions: Mapped[List["ChatSession"]] = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    tasks: Mapped[List["SACTask"]] = relationship("SACTask", back_populates="user", passive_deletes=True)
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    projects: Mapped[List["Project"]] = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    session_inputs: Mapped[List["SessionInput"]] = relationship("SessionInput", back_populates="user", cascade="all, delete-orphan")
    feedbacks: Mapped[List["MessageFeedback"]] = relationship("MessageFeedback", back_populates="user", cascade="all, delete-orphan")
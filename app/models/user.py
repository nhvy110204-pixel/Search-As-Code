from __future__ import annotations

import uuid
from typing import List, TYPE_CHECKING
from sqlalchemy import String, Boolean, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, AIEntityMixin

if TYPE_CHECKING:
    from .api_key import APIKey
    from .chat_session import ChatSession
    from .document import Document
    from .sac_task import SACTask

class User(AIEntityMixin, Base):
    """Quản lý thông tin tài khoản người dùng chính trong hệ thống."""
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)

    api_keys: Mapped[List["APIKey"]] = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    chat_sessions: Mapped[List["ChatSession"]] = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    tasks: Mapped[List["SACTask"]] = relationship("SACTask", back_populates="user")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="user", cascade="all, delete-orphan")
from __future__ import annotations

import uuid
from typing import Any, List, Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.enums import ProjectStatus
from .base import Base, AIEntityMixin

if TYPE_CHECKING:
    from .audit_log import AuditLog
    from .chat_session import ChatSession
    from .document import Document
    from .sac_task import SACTask
    from .user import User


class Project(AIEntityMixin, Base):
    """
    Knowledge workspace trung tâm cho mô hình NotebookLM-style.
    Một user có nhiều project, và mỗi project gom nhiều document thành một knowledge scope.
    """
    __tablename__ = "projects"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ProjectStatus] = mapped_column(
        String(20),
        default=ProjectStatus.ACTIVE,
        server_default=text("'active'"),
        nullable=False,
    )

    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    owner: Mapped["User"] = relationship("User", back_populates="projects")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="project", cascade="all, delete-orphan")
    documents: Mapped[List["Document"]] = relationship(
        "Document",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Document.created_at",
    )
    chat_sessions: Mapped[List["ChatSession"]] = relationship(
        "ChatSession",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ChatSession.created_at",
    )
    tasks: Mapped[List["SACTask"]] = relationship(
        "SACTask",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="SACTask.created_at",
    )

    __table_args__ = (
        Index("idx_projects_owner_status", "owner_user_id", "status"),
    )
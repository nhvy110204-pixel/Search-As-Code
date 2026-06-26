from __future__ import annotations

import uuid
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, String, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, AuditLogMixin

if TYPE_CHECKING:
    from .user import User
    from .project import Project


class AuditLog(AuditLogMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True
    )  # e.g., "document.delete", "api_key.create"
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )  # "success" | "failed"

    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False
    )

    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="audit_logs")
    project: Mapped[Optional["Project"]] = relationship("Project", back_populates="audit_logs")

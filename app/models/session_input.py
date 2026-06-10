from __future__ import annotations

import uuid
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.enums import InputSourceType, InputStatus
from .base import Base, AIEntityMixin

if TYPE_CHECKING:
    from .chat_session import ChatSession
    from .user import User


class SessionInput(AIEntityMixin, Base):
    """
    Transient input cho một chat session.
    Dùng cho text, OCR image/PDF, voice transcript, và file upload tạm thời.
    Input này chỉ phục vụ phiên chat hiện tại, không phải knowledge dài hạn của project.
    """
    __tablename__ = "session_inputs"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_type: Mapped[InputSourceType] = mapped_column(
        String(20),
        nullable=False,
        default=InputSourceType.DOCUMENT,
        server_default=text("'document'"),
    )
    status: Mapped[InputStatus] = mapped_column(
        String(20),
        nullable=False,
        default=InputStatus.UPLOADED,
        server_default=text("'uploaded'"),
    )

    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    raw_storage_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    normalized_text_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ocr_json_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    transcript_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(nullable=True)

    processing_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="inputs")
    user: Mapped["User"] = relationship("User", back_populates="session_inputs")

    __table_args__ = (
        Index("idx_session_inputs_session_status", "session_id", "status"),
        Index("idx_session_inputs_user_created", "user_id", "created_at"),
    )
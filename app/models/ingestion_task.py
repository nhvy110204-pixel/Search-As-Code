from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text, Float, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.enums import IngestionTaskStatus

from .base import Base, AIEntityMixin

if TYPE_CHECKING:
    from .document import Document
    from .project import Project
    from .user import User

class IngestionTask(AIEntityMixin, Base):
    """
    Quản lý vòng đời và trạng thái chi tiết của một tác vụ xử lý tài liệu chạy ngầm (Background Job).
    Giúp UI cập nhật tiến độ (Progress Bar) theo thời gian thực cho User.
    """
    __tablename__ = "ingestion_tasks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tác vụ này thuộc về tài liệu nào"
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    status: Mapped[IngestionTaskStatus] = mapped_column(
        String(30), 
        default=IngestionTaskStatus.PENDING, 
        server_default=text("'pending'"), 
        nullable=False,
        comment="Trạng thái chi tiết: pending, parsing, summarizing, chunking, embedding, completed, failed"
    )
    
    progress: Mapped[float] = mapped_column(
        Float, 
        default=0.0, 
        server_default=text("0.0"), 
        nullable=False,
        comment="Tiến độ xử lý từ 0.0 đến 100.0"
    )
    
    error_message: Mapped[Optional[str]] = mapped_column(
        Text, 
        nullable=True, 
        comment="Lưu vết stack trace ngắn nếu pipeline gặp lỗi"
    )
 
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="Thời điểm worker bắt đầu nhặt task"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        comment="Thời điểm hoàn thành hoặc thất bại"
    )

    chunking_strategy: Mapped[str] = mapped_column(String(50), default="structural_markdown", server_default=text("'structural_markdown'"))
    embedding_model: Mapped[str] = mapped_column(String(100), default="bge-small-en-v1.5", server_default=text("'bge-small-en-v1.5'"))

    document: Mapped["Document"] = relationship("Document")
    project: Mapped["Project"] = relationship("Project")
    user: Mapped["User"] = relationship("User")
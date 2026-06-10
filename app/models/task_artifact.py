from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Integer, DECIMAL, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, UUIDMixin, TimestampMixin

if TYPE_CHECKING:
    from .sac_task import SACTask

class TaskArtifact(UUIDMixin, TimestampMixin, Base):
    """
    Registry Index: Sau khi Sandbox dọn dẹp (Cleanup), các file dữ liệu đầu ra cốt lõi (JSON, CSV, PDF)
    sẽ được đẩy ra Object Storage an toàn. Thực thể này quản lý metadata và điểm tin cậy (Confidence Score) của file đó.
    """
    __tablename__ = "task_artifacts"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sac_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Tên file kết xuất (VD: cve_analysis.json)")
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="Đường dẫn file trên Storage Service")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream", server_default=text("'application/octet-stream'"), nullable=False)

    coverage_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 4), nullable=True)
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 4), nullable=True)

    task: Mapped["SACTask"] = relationship("SACTask", back_populates="artifacts")

    __table_args__ = (
        Index("uq_task_artifact_name", "task_id", "file_name", unique=True),
    )
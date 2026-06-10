from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Any, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text, Integer, DateTime, DECIMAL, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, AIEntityMixin
from app.shared.enums import TaskStatus

if TYPE_CHECKING:
    from .api_key import APIKey
    from .sdk_operation import SDKOperation
    from .task_artifact import TaskArtifact
    from .project import Project
    from .user import User

class SACTask(AIEntityMixin, Base):
    """
    Control Plane Entity: Quản lý toàn bộ vòng đời thực thi của một SaC Task (Thread ID trong LangGraph).
    Lưu trữ cấu hình, trạng thái cộng dồn (Aggregate Cache Metrics) để tránh thắt nút cổ chai hiệu năng của Database.
    """
    __tablename__ = "sac_tasks"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("user_api_keys.id", ondelete="SET NULL"), nullable=True, index=True)
    
    directive: Mapped[str] = mapped_column(Text, nullable=False, comment="Yêu cầu tìm kiếm gốc từ khách hàng")
    status: Mapped[TaskStatus] = mapped_column(String(20), default=TaskStatus.PENDING, server_default=text("'pending'"), nullable=False)
    
    # Cấu hình vòng lặp và dữ liệu nền tảng lưu dưới dạng JSONB linh hoạt
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    
    # Metrics cộng dồn theo thời gian thực (Cập nhật ở cuối mỗi Turn bởi Worker)
    total_steps: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    total_cost_usd: Mapped[Decimal] = mapped_column(DECIMAL(10, 6), default=Decimal("0.0"), server_default=text("0.0"), nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="tasks")
    project: Mapped["Project"] = relationship("Project", back_populates="tasks")
    api_key: Mapped[Optional["APIKey"]] = relationship("APIKey", back_populates="tasks")
    operations: Mapped[List["SDKOperation"]] = relationship("SDKOperation", back_populates="task", cascade="all, delete-orphan", order_by="SDKOperation.turn_number")
    artifacts: Mapped[List["TaskArtifact"]] = relationship("TaskArtifact", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_tasks_user_status", "user_id", "status"),
        Index("idx_tasks_status_created", "status", "created_at"),
    )
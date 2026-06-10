from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Integer, DateTime, DECIMAL, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, UUIDMixin

if TYPE_CHECKING:
    from .sac_task import SACTask

class SDKOperation(UUIDMixin, Base):
    """
    Append-Only Audit Log: Lưu vết toàn bộ lịch sử các thao tác hàm SDK mà Model tự viết mã thực thi trong Sandbox.
    """
    __tablename__ = "sdk_operations"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sac_tasks.id", ondelete="CASCADE"), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="Vòng lặp ReAct thứ mấy")
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="Tên hàm SDK được gọi, VD: web_search, fetch_page")
    
    input_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    result_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 6), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    task: Mapped["SACTask"] = relationship("SACTask", back_populates="operations")

    __table_args__ = (
        Index("idx_operations_task_turn", "task_id", "turn_number"),
    )
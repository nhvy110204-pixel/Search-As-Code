from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import Boolean, ForeignKey, String, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, UUIDMixin, TimestampMixin, SoftDeleteMixin

if TYPE_CHECKING:
    from .sac_task import SACTask
    from .user import User

class APIKey(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """
    Quản lý các Token/Credentials để Client gọi vào API.
    Lưu dạng băm SHA-256 (key_hash).
    """
    __tablename__ = "user_api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="Tên gợi nhớ (VD: Prod-Key)")
    
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    prefix: Mapped[str] = mapped_column(String(8), nullable=False, comment="Tiền tố nhận diện nhanh, VD: sac_live_")
    
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="api_keys")
    tasks: Mapped[List["SACTask"]] = relationship("SACTask", back_populates="api_key")
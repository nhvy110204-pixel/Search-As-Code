from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING
from sqlalchemy import ForeignKey, Text, String, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, AIEntityMixin
from app.shared.enums import MemoryType

if TYPE_CHECKING:
    from .user import User

class UserMemory(AIEntityMixin, Base):
    """
    Semantic Long-term Memory (Global): Vùng nhớ dài hạn mang tính ngữ nghĩa toàn cục của User.
    Dùng cho các thông tin chung xuyên suốt qua nhiều ngày chat của User (Không bị bó buộc vào Project nào).
    Vector embedding được lưu trong Qdrant, Postgres chỉ lưu metadata + embedding_id reference.
    """
    __tablename__ = "user_memories"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_type: Mapped[MemoryType] = mapped_column(String(20), default=MemoryType.FACT, server_default=text("'fact'"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Nội dung văn bản được ghi nhớ")
    
    # Qdrant embedding_id (UUID reference)
    embedding_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True, comment="Reference to vector in Qdrant")

    user: Mapped["User"] = relationship("User")

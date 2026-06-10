from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING
from sqlalchemy import ForeignKey, Text, String, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]
from .base import Base, AIEntityMixin
from app.shared.enums import MemoryType

if TYPE_CHECKING:
    from .user import User

class UserMemory(AIEntityMixin, Base):
    """
    Semantic Long-term Memory (Global): Vùng nhớ dài hạn mang tính ngữ nghĩa toàn cục của User.
    Dùng cho các thông tin chung xuyên suốt qua nhiều ngày chat của User (Không bị bó buộc vào Project nào).
    """
    __tablename__ = "user_memories"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_type: Mapped[MemoryType] = mapped_column(String(20), default=MemoryType.FACT, server_default=text("'fact'"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Nội dung văn bản được ghi nhớ")
    
    # Lưu Vector Embedding 1536 chiều (Phù hợp text-embedding-3-small hoặc tương đương)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index(
            "idx_user_memories_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
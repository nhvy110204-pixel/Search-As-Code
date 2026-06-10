from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING
from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, UUIDMixin, TimestampMixin

if TYPE_CHECKING:
    from .user import User

class UserPreference(UUIDMixin, TimestampMixin, Base):
    """
    Explicit Long-term Memory: Lưu trữ các cấu hình, sở thích cứng, tường minh của User.
    Giúp AI cá nhân hóa câu trả lời (UI Theme, Default LLM Model, Custom System Prompt...).
    """
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), 
        unique=True,  # 1-1 với User
        nullable=False,
        index=True
    )
    
    # Lưu động cấu hình: {"theme": "dark", "preferred_language": "vi", "programming_style": "functional"}
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False
    )

    user: Mapped["User"] = relationship("User")
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import AIEntityMixin, Base

if TYPE_CHECKING:
    from .user import User


class AuthRefreshToken(AIEntityMixin, Base):
    __tablename__ = "auth_refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_token_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    user: Mapped["User"] = relationship("User")
    replaced_by_token: Mapped[Optional["AuthRefreshToken"]] = relationship("AuthRefreshToken", remote_side="AuthRefreshToken.id")

    __table_args__ = (
        Index("idx_auth_refresh_tokens_user_active", "user_id", "revoked_at", "expires_at"),
    )

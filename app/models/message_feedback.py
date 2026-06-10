from __future__ import annotations

import uuid
from typing import Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, UUIDMixin, TimestampMixin

if TYPE_CHECKING:
    from .chat_message import ChatMessage

class MessageFeedback(UUIDMixin, TimestampMixin, Base):
    """
    Hệ thống thu thập dữ liệu phản hồi người dùng (RLHF Data Loop).
    Kho lưu trữ quý giá để đội phát triển AI lấy ra tinh chỉnh Prompt / Fine-tune Model.
    """
    __tablename__ = "message_feedbacks"

    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    is_positive: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="True = Thumbs Up, False = Thumbs Down")
    reason_tags: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Tag lỗi nhanh (VD: Sai kiến thức, Code bug...)")
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Ý kiến đóng góp bằng văn bản của khách hàng")

    message: Mapped["ChatMessage"] = relationship("ChatMessage", back_populates="feedback")
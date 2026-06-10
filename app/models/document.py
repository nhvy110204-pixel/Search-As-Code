from __future__ import annotations

import uuid

from typing import Any, List, Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text, Integer, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base, AIEntityMixin, UUIDMixin
from app.shared.enums import DocumentStatus

if TYPE_CHECKING:
    from .chat_session import ChatSession
    from .user import User

class Document(AIEntityMixin, Base):
    """
    Quản lý một file tài liệu lớn (PDF/Docx/TXT) được upload để làm kho tri thức cho chatbot.
    """
    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Tên tài liệu / Tên Project")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Mô tả tóm tắt nội dung tài liệu")
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="Đường dẫn file trên Object Storage S3/MinIO")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(String(20), default=DocumentStatus.PENDING, server_default=text("'pending'"), nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="documents")

    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index"
    )

    chat_sessions: Mapped[List["ChatSession"]] = relationship("ChatSession", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_documents_user_status", "user_id", "status"),
    )


class DocumentChunk(UUIDMixin, Base):
    """
    Các đoạn văn nhỏ (Text Chunks) được cắt từ file lớn kèm Vector Embedding độc lập của dự án đó.
    """
    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="Thứ tự của đoạn văn phục vụ việc tái cấu trúc ngữ cảnh")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Nội dung chữ thô của đoạn")
    embedding: Mapped[list[float]] = mapped_column(JSONB, nullable=False)

    meta_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_document_id", "document_id"),
    )
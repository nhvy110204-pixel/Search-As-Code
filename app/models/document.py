from __future__ import annotations

import uuid

from typing import Any, Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text, Integer, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector  

from .base import Base, AIEntityMixin, UUIDMixin, TimestampMixin
from app.shared.enums import DocumentStatus

if TYPE_CHECKING:
    from .project import Project
    from .user import User

class Document(AIEntityMixin, Base):
    """
    Quản lý một file tài liệu lớn (PDF/Docx/TXT/MD) được upload vào một Project.
    Mỗi document sẽ được convert sang markdown và chunk để phục vụ retrieval.
    """
    __tablename__ = "documents"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Tên tài liệu / Tên Project")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Mô tả tóm tắt nội dung tài liệu")
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False, comment="Đường dẫn file trên Object Storage S3/MinIO")
    markdown_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True, comment="Đường dẫn file markdown sau khi convert")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(String(20), default=DocumentStatus.PENDING, server_default=text("'pending'"), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)

    processing_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="documents")
    project: Mapped["Project"] = relationship("Project", back_populates="documents")

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index"
    )

    __table_args__ = (
        Index("idx_documents_project_status", "project_id", "status"),
        Index("idx_documents_user_status", "user_id", "status"),
    )


class DocumentChunk(UUIDMixin, TimestampMixin, Base):
    """
    Các đoạn văn nhỏ (Text Chunks) được cắt từ file lớn kèm Vector Embedding độc lập của dự án đó.
    """
    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="Thứ tự của đoạn văn phục vụ việc tái cấu trúc ngữ cảnh")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Nội dung chữ thô của đoạn")
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    meta_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_document_id", "document_id"),
        Index("idx_chunks_document_hash", "document_id", "chunk_hash", unique=True),
        Index(
            "idx_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
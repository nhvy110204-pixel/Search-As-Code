from __future__ import annotations

import uuid

from typing import Any, Optional, TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text, Integer, Index, text, Boolean, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, AIEntityMixin
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
    file_content: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True, comment="Nội dung file gốc lưu trong PostgreSQL BYTEA (max 100MB)")
    is_compressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False, comment="Đánh dấu nếu file_content đã được nén gzip")
    markdown_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Nội dung markdown sau khi parse từ file gốc")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, comment="Kích thước storage thực tế để tracking quota")
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(String(30), default=DocumentStatus.PENDING, server_default=text("'pending'"), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    blake3_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="Mã băm blake3 của file gốc để tránh xử lý trùng lặp")
    has_partial_failures: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False, comment="Đánh dấu nếu có chunk embedding thất bại")

    processing_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
        comment="Metadata xử lý: global_summary, document-level metadata"
    )

    pipeline_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
        comment="Checkpoint state để resume pipeline từ step bị crash"
    )

    user: Mapped["User"] = relationship("User", back_populates="documents")
    project: Mapped["Project"] = relationship("Project", back_populates="documents")

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index"
    )

    __table_args__ = (
        Index("idx_documents_project_status", "project_id", "status"),
        Index("idx_documents_user_status", "user_id", "status"),
        Index("idx_documents_project_hash_unique", "project_id", "blake3_hash", unique=True),
    )


class DocumentChunk(AIEntityMixin, Base):
    """
    Các đoạn văn nhỏ (Text Chunks) được cắt từ file lớn kèm Vector Embedding độc lập của dự án đó.
    Vector embedding được lưu trong Qdrant, Postgres chỉ lưu metadata + embedding_id reference.
    """
    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="Thứ tự của đoạn văn phục vụ việc tái cấu trúc ngữ cảnh")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Nội dung chữ thô của đoạn")
    enriched_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Nội dung sau khi enrich với title + global summary")
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="Blake3 hash của chunk content cho dedup")
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"), nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embed_status: Mapped[str] = mapped_column(String(20), default="pending", server_default=text("'pending'"), nullable=False, comment="pending, done, failed")
    chunk_source: Mapped[str] = mapped_column(String(50), default="auto", server_default=text("'auto'"), nullable=False, comment="auto vs existing (cho chunk dedup)")

    # Qdrant embedding_id (UUID reference)
    embedding_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True, comment="Reference to vector in Qdrant")

    meta_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_document_id", "document_id"),
        Index("idx_chunks_hash_unique", "chunk_hash", unique=True),
    )

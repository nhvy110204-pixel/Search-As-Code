from __future__ import annotations

import uuid

from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, AIEntityMixin

if TYPE_CHECKING:
    from .document import Document
    from .document import DocumentChunk

class DocumentChunkLink(AIEntityMixin, Base):
    """
    Link table để share chunks giữa nhiều documents.
    Hỗ trợ dedup: một chunk có thể được link bởi nhiều documents khác nhau.
    """
    __tablename__ = "document_chunk_links"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    document: Mapped["Document"] = relationship("Document")
    chunk: Mapped["DocumentChunk"] = relationship("DocumentChunk")

    __table_args__ = (
        Index("idx_doc_chunk_link_unique", "document_id", "chunk_id", unique=True),
    )

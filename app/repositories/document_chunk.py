from typing import Optional, List, Dict, Any
from uuid import UUID

from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk
from app.schemas.dto.document_chunk import DocumentChunkCreate, DocumentChunkUpdate

from .base import BaseRepository


class DocumentChunkRepository(
    BaseRepository[
        DocumentChunk,
        DocumentChunkCreate,
        DocumentChunkUpdate,
    ]
):

    def __init__(self, db: Session):
        super().__init__(DocumentChunk, db)

    def get_by_embedding_id(
        self,
        embedding_id: UUID,
    ) -> Optional[DocumentChunk]:
    
        return self.get_by(
            embedding_id=embedding_id
        )

    def get_by_document(
        self,
        document_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> List[DocumentChunk]:

        query = (
            self._get_query()
            .where(
                DocumentChunk.document_id == document_id
            )
            .order_by(
                DocumentChunk.chunk_index.asc()
            )
            .offset(skip)
            .limit(limit)
        )

        return self.db.execute(query).scalars().all()

    def get_chunk_count_by_document(
        self,
        document_id: UUID,
    ) -> int:
        
        return self.count(
            filters={
                "document_id": document_id
            }
        )

    def delete_by_document(
        self,
        document_id: UUID,
        hard: bool = False,
    ) -> int:

        if hard:
            stmt = delete(DocumentChunk).where(
                DocumentChunk.document_id == document_id
            )

        else:
            stmt = (
                update(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.is_deleted.is_(False),
                )
                .values(
                    is_deleted=True,
                    deleted_at=func.now(),
                )
            )

        result = self.db.execute(stmt)

        self.db.flush()

        return result.rowcount or 0

    def list_document_chunks(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> tuple[list[DocumentChunk], int]:
        """Paginate document chunks. Returns (chunks, total)."""
        query = select(DocumentChunk)

        if filters:
            if "document_id" in filters and filters["document_id"] is not None:
                query = query.filter(DocumentChunk.document_id == filters["document_id"])

        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.execute(count_query).scalar() or 0

        query = query.order_by(DocumentChunk.chunk_index.asc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = self.db.execute(query).scalars().all()

        return list(results), total
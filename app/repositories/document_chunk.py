from typing import Optional, List, Dict, Any, Tuple
from uuid import UUID

from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

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

    def find_by_chunk_hash(self, chunk_hash: str) -> Optional[DocumentChunk]:

        query = select(DocumentChunk).where(
            DocumentChunk.chunk_hash == chunk_hash,
            DocumentChunk.is_deleted.is_(False)
        )
        return self.db.execute(query).scalar_one_or_none()

    def insert_chunk_if_not_exists(self, chunk_data: Dict[str, Any]) -> Tuple[DocumentChunk, bool]:

        chunk_hash = chunk_data["chunk_hash"]
        
        stmt = insert(DocumentChunk).values(chunk_data)
        stmt = stmt.on_conflict_do_nothing(index_elements=["chunk_hash"])
        
        result = self.db.execute(stmt)
        
        if result.rowcount == 0:
            existing = self.find_by_chunk_hash(chunk_hash)
            return existing, False
        else:
            new_chunk = self.find_by_chunk_hash(chunk_hash)
            return new_chunk, True

    def batch_insert_chunks_if_not_exists(self, chunks: List[Dict[str, Any]]) -> List[Tuple[DocumentChunk, bool]]:

        if not chunks:
            return []
        
        results = []
        chunk_hashes = {chunk["chunk_hash"] for chunk in chunks}
        
        stmt = insert(DocumentChunk).values(chunks)
        stmt = stmt.on_conflict_do_nothing(index_elements=["chunk_hash"])
        self.db.execute(stmt)
        self.db.flush()
        
        for chunk_hash in chunk_hashes:
            chunk = self.find_by_chunk_hash(chunk_hash)
            if chunk:
                original_chunk = next((c for c in chunks if c["chunk_hash"] == chunk_hash), None)
                if original_chunk and chunk.document_id == original_chunk.get("document_id"):
                    results.append((chunk, True))
                else:
                    results.append((chunk, False))
        
        return results

    def update_embed_status(self, chunk_id: UUID, status: str) -> None:
        stmt = update(DocumentChunk).where(DocumentChunk.id == chunk_id).values(embed_status=status)
        self.db.execute(stmt)
        self.db.flush()

    def update_enriched_content(self, chunk_id: UUID, content: str) -> None:
        stmt = update(DocumentChunk).where(DocumentChunk.id == chunk_id).values(enriched_content=content)
        self.db.execute(stmt)
        self.db.flush()
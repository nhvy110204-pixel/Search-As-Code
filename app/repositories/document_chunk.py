from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk
from app.schemas.dto.chunk_embedding import ChunkEmbeddingCreateDTO

from .base import BaseRepository


class DocumentChunkRepository(
    BaseRepository[
        DocumentChunk,
        ChunkEmbeddingCreateDTO,
        ChunkEmbeddingCreateDTO,
    ]
):

    def __init__(self, db: Session):
        super().__init__(DocumentChunk, db)

    def create_with_embedding_id(
        self,
        document_id: UUID,
        chunk_index: int,
        content: str,
        embedding_id: UUID,
        chunk_hash: str,
        token_count: int = 0,
        page_number: Optional[int] = None,
        meta_data: Optional[dict] = None,
    ) -> DocumentChunk:

        chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=chunk_index,
            content=content,
            embedding_id=embedding_id,
            chunk_hash=chunk_hash,
            token_count=token_count,
            page_number=page_number,
            meta_data=meta_data or {},
        )

        self.db.add(chunk)
        self.db.flush()
        self.db.refresh(chunk)

        return chunk

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

    def update_embedding_id(
        self,
        chunk_id: UUID,
        embedding_id: UUID,
    ) -> Optional[DocumentChunk]:

        chunk = self.get(chunk_id)

        if chunk is None:
            return None

        chunk.embedding_id = embedding_id

        self.db.flush()
        self.db.refresh(chunk)

        return chunk

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
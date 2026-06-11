from typing import Optional, List, Any
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk
from app.repositories.document_chunk import DocumentChunkRepository
from app.services.core.base import BaseService


class DocumentChunkService(BaseService[DocumentChunk, Any, Any]):
    def __init__(self, db: Session):
        super().__init__(DocumentChunkRepository(db))

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
        return self.repo.create_with_embedding_id(
            document_id=document_id,
            chunk_index=chunk_index,
            content=content,
            embedding_id=embedding_id,
            chunk_hash=chunk_hash,
            token_count=token_count,
            page_number=page_number,
            meta_data=meta_data,
        )

    def update_embedding_id(self, chunk_id: UUID, embedding_id: UUID) -> Optional[DocumentChunk]:
        return self.repo.update_embedding_id(chunk_id, embedding_id)

    def get_by_embedding_id(self, embedding_id: UUID) -> Optional[DocumentChunk]:
        return self.repo.get_by_embedding_id(embedding_id)

    def get_by_document(self, document_id: UUID, skip: int = 0, limit: int = 100) -> List[DocumentChunk]:
        return self.repo.get_by_document(document_id, skip=skip, limit=limit)

    def delete_by_document(self, document_id: UUID, hard: bool = False) -> int:
        return self.repo.delete_by_document(document_id, hard=hard)

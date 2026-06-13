import uuid
from typing import Optional, List, Any, Dict
from app.models.document import DocumentChunk
from app.repositories.document_chunk import DocumentChunkRepository
from app.schemas.dto.document_chunk import DocumentChunkCreate, DocumentChunkUpdate, DocumentChunkListResponse
from app.services.core.base import BaseService


class DocumentChunkService(BaseService[DocumentChunk, DocumentChunkCreate, DocumentChunkUpdate]):
    def __init__(self, repository: DocumentChunkRepository):
        super().__init__(repository)
        self.chunk_repo = repository

    def get_chunks_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> DocumentChunkListResponse:
        """Domain method: paginated chunk list."""
        return self.chunk_repo.list_document_chunks(page=page, page_size=page_size, filters=filters)

    def get_by_embedding_id(self, embedding_id: uuid.UUID) -> Optional[DocumentChunk]:
        """Domain method: get chunk by embedding ID."""
        return self.chunk_repo.get_by_embedding_id(embedding_id)

    def get_by_document(self, document_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[DocumentChunk]:
        """Domain method: get chunks by document."""
        return self.chunk_repo.get_by_document(document_id, skip=skip, limit=limit)

    def delete_by_document(self, document_id: uuid.UUID, hard: bool = False) -> int:
        """Domain method: delete all chunks of a document."""
        return self.chunk_repo.delete_by_document(document_id, hard=hard)

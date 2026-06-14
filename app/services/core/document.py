import uuid
from typing import Optional, Any, Dict
from app.models.document import Document
from app.repositories.document import DocumentRepository
from app.schemas.dto.document import DocumentCreate, DocumentUpdate, DocumentListResponse
from app.services.core.base import BaseService


class DocumentService(BaseService[Document, DocumentCreate, DocumentUpdate]):
    def __init__(self, repository: DocumentRepository):
        super().__init__(repository)
        self.doc_repo = repository

    def get_documents_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> DocumentListResponse:
        from app.schemas.dto.document import DocumentResponse
        documents, total = self.doc_repo.list_documents(page=page, page_size=page_size, filters=filters)
        document_responses = [DocumentResponse.model_validate(d) for d in documents]
        return DocumentListResponse(
            items=document_responses,
            total=total,
            page=page,
            page_size=page_size
        )

    def get_by_project(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100) -> list[Document]:
        return self.doc_repo.get_by_project(project_id, skip=skip, limit=limit)

    def increment_chunk_count(self, document_id: uuid.UUID, delta: int = 1) -> Optional[Document]:
        db_obj = self.get(document_id)
        if not db_obj:
            return None
        db_obj.chunk_count = (db_obj.chunk_count or 0) + delta
        return self.doc_repo.update(db_obj, {})

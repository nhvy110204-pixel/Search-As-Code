import uuid
import logging
from typing import Optional, Any, Dict
from app.models.document import Document
from app.repositories.document import DocumentRepository
from app.schemas.dto.document import DocumentCreate, DocumentUpdate, DocumentResponse, DocumentListResponse
from app.services.core.base import BaseService
from app.core.logger import service_boundary
from app.services.core.redis_service import redis_cache_service

logger = logging.getLogger(__name__)


class DocumentService(BaseService[Document, DocumentCreate, DocumentUpdate]):
    def __init__(self, repository: DocumentRepository):
        super().__init__(repository)
        self.doc_repo = repository

    def _invalidate_cache(self, project_id: uuid.UUID) -> None:
        if not redis_cache_service.redis:
            return
        try:
            cache_key = f"project:{project_id}:documents_metadata"
            redis_cache_service.redis.delete(cache_key)
            logger.info(f"Invalidated project documents metadata cache for project_id={project_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate project documents metadata cache for project_id={project_id}: {e}")

    @service_boundary("Create Entity")
    def create(self, obj_in: DocumentCreate) -> Document:
        doc = super().create(obj_in)
        if doc and doc.project_id:
            self._invalidate_cache(doc.project_id)
        return doc

    @service_boundary("Update Entity")
    def update(self, id: uuid.UUID, obj_in: DocumentUpdate | Dict[str, Any]) -> Optional[Document]:
        doc = self.get(id)
        if not doc:
            return None
        old_project_id = doc.project_id
        updated_doc = super().update(id, obj_in)
        if updated_doc:
            if old_project_id:
                self._invalidate_cache(old_project_id)
            if updated_doc.project_id and updated_doc.project_id != old_project_id:
                self._invalidate_cache(updated_doc.project_id)
        return updated_doc

    @service_boundary("Delete Entity")
    def delete(self, id: uuid.UUID, hard: bool = False) -> bool:
        doc = self.get(id)
        if not doc:
            return False
        project_id = doc.project_id
        success = super().delete(id, hard=hard)
        if success and project_id:
            self._invalidate_cache(project_id)
        return success

    @service_boundary("Get Documents Paginated")
    def get_documents_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> DocumentListResponse:
        documents, total = self.doc_repo.list_documents(page=page, page_size=page_size, filters=filters)
        document_responses = [DocumentResponse.model_validate(d) for d in documents]
        return DocumentListResponse(
            items=document_responses,
            total=total,
            page=page,
            page_size=page_size
        )

    @service_boundary("Get Documents by Project")
    def get_by_project(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100) -> list[Document]:
        return self.doc_repo.get_by_project(project_id, skip=skip, limit=limit)

    @service_boundary("Increment Document Chunk Count")
    def increment_chunk_count(self, document_id: uuid.UUID, delta: int = 1) -> Optional[Document]:
        db_obj = self.get(document_id)
        if not db_obj:
            return None
        db_obj.chunk_count = (db_obj.chunk_count or 0) + delta
        return self.doc_repo.update(db_obj, {})

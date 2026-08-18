import uuid
import logging
from typing import Optional, Any, Dict
from app.models.document import Document
from app.repositories.document import DocumentRepository
from app.schemas.dto.document import DocumentCreate, DocumentUpdate, DocumentResponse, DocumentListResponse
from app.services.core.base import BaseService
from app.core.logger import service_boundary
from app.services.core.redis_service import redis_cache_service
from app.core.audit import log_audit_event
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, MatchAny
from app.core.qdrant import qdrant_manager
from app.config.settings import settings

logger = logging.getLogger(__name__)


class DocumentService(BaseService[Document, DocumentCreate, DocumentUpdate]):
    def __init__(self, repository: DocumentRepository, uow=None):
        super().__init__(repository, uow)
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
    def create(self, obj_in: DocumentCreate, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Document:
        try:
            doc = super().create(obj_in)
            if doc and doc.project_id:
                self._invalidate_cache(doc.project_id)
            if self.uow:
                log_audit_event(
                    uow=self.uow,
                    user_id=obj_in.user_id,
                    project_id=obj_in.project_id,
                    action="document.upload",
                    status="success",
                    context={
                        "document_id": str(doc.id) if doc else None,
                        "file_name": obj_in.file_name,
                        "file_size_bytes": obj_in.file_size_bytes
                    },
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            return doc
        except Exception as e:
            if self.uow:
                log_audit_event(
                    uow=self.uow,
                    user_id=obj_in.user_id,
                    project_id=obj_in.project_id,
                    action="document.upload_failed",
                    status="failed",
                    context={
                        "file_name": obj_in.file_name,
                        "error": str(e)
                    },
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            raise e

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
    def delete(
        self,
        id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        hard: bool = False
    ) -> bool:

        doc = self.repo.get(id, include_deleted=True)
        
        # Always attempt to clean up Qdrant vectors for this document_id
        try:
            filter_cond = Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(id))
                    )
                ]
            )
            qdrant_manager.delete_vectors_by_filter(
                collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                filter_condition=filter_cond
            )
        except Exception as qerr:
            logger.warning(f"Failed to delete Qdrant vectors for doc {id}: {qerr}")

        if not doc:
            # Document is already not in DB (idempotent delete success)
            return True

        project_id = doc.project_id
        success = super().delete(id, hard=hard)
        if success and project_id:
            self._invalidate_cache(project_id)

        if self.uow and success:
            log_audit_event(
                uow=self.uow,
                user_id=user_id,
                project_id=project_id,
                action="document.delete",
                status="success",
                context={
                    "document_id": str(id),
                    "file_name": doc.file_name,
                    "hard_delete": hard
                },
                ip_address=ip_address,
                user_agent=user_agent
            )
        return success or True


    @service_boundary("Batch Delete Documents")
    def batch_delete(
        self,
        document_ids: list[uuid.UUID],
        user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        hard: bool = False
    ) -> Dict[str, Any]:

        deleted_ids = []
        project_ids_to_invalidate = set()

        for doc_id in document_ids:
            doc = self.get(doc_id)
            if doc:
                if doc.project_id:
                    project_ids_to_invalidate.add(doc.project_id)
                if super().delete(doc_id, hard=hard):
                    deleted_ids.append(doc_id)

        for pid in project_ids_to_invalidate:
            self._invalidate_cache(pid)

        # Cleanup Qdrant vectors for all deleted documents
        if deleted_ids:
            try:
                filter_cond = Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchAny(any=[str(did) for did in deleted_ids])
                        )
                    ]
                )
                qdrant_manager.delete_vectors_by_filter(
                    collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                    filter_condition=filter_cond
                )
            except Exception as qerr:
                logger.warning(f"Failed to delete Qdrant vectors for batch: {qerr}")

        if self.uow and deleted_ids:
            log_audit_event(
                uow=self.uow,
                user_id=user_id,
                project_id=list(project_ids_to_invalidate)[0] if project_ids_to_invalidate else None,
                action="document.batch_delete",
                status="success",
                context={
                    "deleted_count": len(deleted_ids),
                    "document_ids": [str(d) for d in deleted_ids],
                    "hard_delete": hard
                },
                ip_address=ip_address,
                user_agent=user_agent
            )

        return {
            "success": True,
            "deleted_count": len(deleted_ids),
            "deleted_document_ids": deleted_ids,
            "message": f"Successfully deleted {len(deleted_ids)} documents and cleaned vector indices"
        }


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

    @service_boundary("Delete Document By Filename")
    def delete_by_filename(
        self,
        filename: str,
        user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:

        documents = self.doc_repo.get_by_filename(filename)
        deleted_chunks = 0

        for doc in documents:
            deleted_chunks += (doc.chunk_count or 1)
            self.delete(id=doc.id, user_id=user_id, ip_address=ip_address, user_agent=user_agent)

        try:
            filter_cond = Filter(
                must=[
                    FieldCondition(
                        key="filename",
                        match=MatchValue(value=filename)
                    )
                ]
            )
            qdrant_manager.delete_vectors_by_filter(
                collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                filter_condition=filter_cond
            )
        except Exception as qerr:
            logger.warning(f"Failed to delete Qdrant vectors for {filename}: {qerr}")

        return {
            "success": True,
            "deleted_chunks": deleted_chunks,
            "filename": filename,
            "message": f"Document '{filename}' and associated vectors deleted successfully"
        }

    @service_boundary("Get Document Preview")
    def get_document_preview(self, id: uuid.UUID) -> Optional[Dict[str, Any]]:
        doc = self.get(id)
        if not doc:
            return None
        content = doc.markdown_content
        if not content and doc.chunks:
            content = "\n\n".join(chunk.content for chunk in doc.chunks if chunk.content)
        
        summary = None
        if doc.processing_metadata and isinstance(doc.processing_metadata, dict):
            summary = doc.processing_metadata.get("global_summary")

        return {
            "id": doc.id,
            "file_name": doc.file_name,
            "mime_type": doc.mime_type,
            "status": doc.status.value if hasattr(doc.status, "value") else str(doc.status),
            "chunk_count": doc.chunk_count or 0,
            "content": content or "",
            "summary": summary,
        }

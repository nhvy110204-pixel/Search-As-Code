import uuid
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.models.document import Document
from app.repositories.base import BaseRepository
from app.schemas.dto.document import DocumentCreate, DocumentUpdate


class DocumentRepository(BaseRepository[Document, DocumentCreate, DocumentUpdate]):
    def __init__(self, db: Session):
        super().__init__(Document, db)

    def get_document(self, id: uuid.UUID) -> Optional[Document]:
        return self.get(id=id)

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
        include_deleted: bool = False,
    ) -> tuple[list[Document], int]:
        query = select(Document)

        if not include_deleted:
            query = query.where(Document.is_deleted.is_(False))

        if filters:
            if "project_id" in filters and filters["project_id"] is not None:
                query = query.filter(Document.project_id == filters["project_id"])
            if "user_id" in filters and filters["user_id"] is not None:
                query = query.filter(Document.user_id == filters["user_id"])
            if "status" in filters and filters["status"] is not None:
                query = query.filter(Document.status == filters["status"])
            if "file_name" in filters and filters["file_name"]:
                query = query.filter(Document.file_name.ilike(f"%{filters['file_name']}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.execute(count_query).scalar() or 0

        query = query.order_by(Document.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = self.db.execute(query).scalars().all()

        return list(results), total


    def get_by_project(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100) -> list[Document]:
        return self.get_multi(filters={"project_id": project_id}, skip=skip, limit=limit)

    def get_active_documents(self, limit: int = 100) -> list[Document]:
        """Lấy danh sách các tài liệu active chưa bị xóa."""
        query = (
            select(Document)
            .where(Document.is_deleted.is_(False))
            .order_by(Document.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(query).scalars().all())

    def get_by_filename(self, filename: str) -> list[Document]:
        """Lấy danh sách các tài liệu theo file_name chính xác và chưa bị xóa."""
        query = select(Document).where(
            Document.file_name == filename,
            Document.is_deleted.is_(False)
        )
        return list(self.db.execute(query).scalars().all())

    def find_by_hash(self, file_hash: str, project_id: uuid.UUID, include_deleted: bool = False) -> Optional[Document]:
        query = select(Document).where(
            Document.blake3_hash == file_hash,
            Document.project_id == project_id
        )
        if not include_deleted:
            query = query.where(Document.is_deleted.is_(False))
        return self.db.execute(query).scalars().first()

    def upsert_document_by_hash(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        file_name: str,
        file_content: bytes,
        file_size_bytes: int,
        mime_type: str,
        file_hash: str,
        storage_size_bytes: Optional[int] = None,
        is_compressed: bool = False,
        description: Optional[str] = None
    ) -> Tuple[Document, bool]:
        # Look for existing document including soft-deleted ones to avoid unique constraint violations
        existing = self.find_by_hash(file_hash, project_id, include_deleted=True)
        if existing:
            # If it was soft-deleted, reactivate it and re-process
            if existing.is_deleted:
                existing.is_deleted = False
                existing.deleted_at = None
                existing.file_name = file_name
                existing.file_content = file_content
                existing.file_size_bytes = file_size_bytes
                existing.storage_size_bytes = storage_size_bytes if storage_size_bytes is not None else file_size_bytes
                existing.mime_type = mime_type
                existing.is_compressed = is_compressed
                existing.description = description
                existing.status = "pending"
                existing.chunk_count = 0
                existing.pipeline_state = {}
                existing.processing_metadata = {}
                self.db.add(existing)
                self.db.flush()
                self.db.refresh(existing)
                return existing, True

            # If existing is in FAILED or PENDING or CANCELLED status, allow re-ingestion
            if existing.status in ["failed", "pending", "cancelled"] or existing.chunk_count == 0:
                existing.file_name = file_name
                existing.file_content = file_content
                existing.status = "pending"
                existing.pipeline_state = {}
                existing.processing_metadata = {}
                self.db.add(existing)
                self.db.flush()
                self.db.refresh(existing)
                return existing, True

            # If existing is already COMPLETED with chunks
            return existing, False

        document_data = {
            "user_id": user_id,
            "project_id": project_id,
            "file_name": file_name,
            "file_content": file_content,
            "file_size_bytes": file_size_bytes,
            "storage_size_bytes": storage_size_bytes if storage_size_bytes is not None else file_size_bytes,
            "mime_type": mime_type,
            "blake3_hash": file_hash,
            "status": "pending",
            "is_compressed": is_compressed,
            "description": description,
        }
        document = self.create(document_data)
        return document, True


    def check_user_quota(self, user_id: uuid.UUID, project_id: uuid.UUID) -> Tuple[bool, int, int]:
        quota_limit = 100 * 1024 * 1024 * 1024  # 100GB default
        
        result = self.db.execute(
            select(func.sum(Document.storage_size_bytes))
            .where(Document.user_id == user_id)
            .where(Document.project_id == project_id)
            .where(Document.is_deleted.is_(False))
        )
        current_usage = result.scalar() or 0
        
        quota_ok = current_usage <= quota_limit
        return quota_ok, current_usage, quota_limit

    def update_pipeline_state(self, document_id: uuid.UUID, state: Dict[str, Any]) -> None:
        stmt = update(Document).where(Document.id == document_id).values(pipeline_state=state)
        self.db.execute(stmt)
        self.db.flush()

    def get_by_ids(self, document_ids: list[uuid.UUID]) -> list[Document]:
        """Lấy danh sách Document theo danh sách ID và chưa bị xóa."""
        if not document_ids:
            return []
        query = select(Document).where(
            Document.id.in_(document_ids),
            Document.is_deleted.is_(False)
        )
        return list(self.db.execute(query).scalars().all())

    def get_project_stats(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Tổng hợp các chỉ số tri thức của một Project (tổng file, tổng chunks, dung lượng, phân loại trạng thái)."""
        docs_query = select(Document).where(
            Document.project_id == project_id,
            Document.is_deleted.is_(False)
        )
        docs = list(self.db.execute(docs_query).scalars().all())

        total_documents = len(docs)
        total_chunks = sum(d.chunk_count or 0 for d in docs)
        total_size_bytes = sum(d.file_size_bytes or 0 for d in docs)

        status_breakdown = {"completed": 0, "processing": 0, "failed": 0, "pending": 0}
        for d in docs:
            status_val = d.status.value if hasattr(d.status, "value") else str(d.status)
            if status_val in ["completed", "completed_with_warnings"]:
                status_breakdown["completed"] += 1
            elif status_val in ["processing", "parsing", "chunking", "embedding", "indexing"]:
                status_breakdown["processing"] += 1
            elif status_val in ["failed", "error"]:
                status_breakdown["failed"] += 1
            else:
                status_breakdown["pending"] += 1

        last_synced_at = None
        if docs:
            last_synced_at = max(d.updated_at for d in docs if d.updated_at)

        return {
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "total_size_bytes": total_size_bytes,
            "status_breakdown": status_breakdown,
            "last_synced_at": last_synced_at
        }


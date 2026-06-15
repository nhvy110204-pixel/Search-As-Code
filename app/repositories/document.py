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
    ) -> tuple[list[Document], int]:
        query = select(Document)

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

    def find_by_hash(self, file_hash: str, project_id: uuid.UUID) -> Optional[Document]:
        query = select(Document).where(
            Document.blake3_hash == file_hash,
            Document.project_id == project_id,
            Document.is_deleted.is_(False)
        )
        return self.db.execute(query).scalar_one_or_none()

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
        existing = self.find_by_hash(file_hash, project_id)
        if existing:
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

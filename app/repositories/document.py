import uuid
from typing import Any, Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
        """
        Paginate documents. Returns (documents, total).
        """
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
        """Lấy danh sách documents theo project."""
        return self.get_multi(filters={"project_id": project_id}, skip=skip, limit=limit)

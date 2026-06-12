from typing import Optional, List, Any
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.document import Document
from app.repositories.base import BaseRepository
from app.services.core.base import BaseService


class DocumentService(BaseService[Document, Any, Any]):
    def __init__(self, db: Session):
        # Use generic BaseRepository for Document if a specific DocumentRepository is not implemented
        super().__init__(BaseRepository(Document, db))

    def get_by_project(self, project_id: UUID, skip: int = 0, limit: int = 100) -> List[Document]:
        return self.repo.get_multi(filters={"project_id": project_id}, skip=skip, limit=limit)

    def increment_chunk_count(self, document_id: UUID, delta: int = 1) -> Optional[Document]:
        db_obj = self.get(document_id)
        if not db_obj:
            return None
        db_obj.chunk_count = (db_obj.chunk_count or 0) + delta
        return self.repo.update(db_obj, {})

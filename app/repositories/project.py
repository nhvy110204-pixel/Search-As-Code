import uuid
from typing import Any, Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.document import Document
from app.models.chat_session import ChatSession
from app.repositories.base import BaseRepository
from app.schemas.dto.project import ProjectCreate, ProjectUpdate

class ProjectRepository(BaseRepository[Project, ProjectCreate, ProjectUpdate]):
    def __init__(self, db: Session):
        super().__init__(Project, db)
    
    def get_project(self, id: uuid.UUID) -> Optional[Project]:
        return self.get(id=id)

    def check_write_permission(self, user_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        project = self.get(id=project_id)
        if not project:
            return False
        return project.owner_user_id == user_id

    def get_project_with_stats(self, id: uuid.UUID) -> Optional[dict[str, Any]]:
        doc_count_subq = (
            select(func.count(Document.id))
            .where(Document.project_id == Project.id, Document.is_deleted == False)
            .scalar_subquery()
            .label("document_count")
        )
        session_count_subq = (
            select(func.count(ChatSession.id))
            .where(ChatSession.project_id == Project.id, ChatSession.is_deleted == False)
            .scalar_subquery()
            .label("session_count")
        )

        query = (
            select(Project, doc_count_subq, session_count_subq)
            .where(Project.id == id, Project.is_deleted == False)
        )
        row = self.db.execute(query).first()
        if not row:
            return None
        project, doc_cnt, sess_cnt = row
        return {
            "id": project.id,
            "owner_user_id": project.owner_user_id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "settings": project.settings or {},
            "document_count": doc_cnt or 0,
            "session_count": sess_cnt or 0,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }

    def list_projects(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Paginate projects with document_count and session_count. Returns (projects_data, total)."""
        doc_count_subq = (
            select(func.count(Document.id))
            .where(Document.project_id == Project.id, Document.is_deleted == False)
            .scalar_subquery()
            .label("document_count")
        )
        session_count_subq = (
            select(func.count(ChatSession.id))
            .where(ChatSession.project_id == Project.id, ChatSession.is_deleted == False)
            .scalar_subquery()
            .label("session_count")
        )

        query = (
            select(Project, doc_count_subq, session_count_subq)
            .where(Project.is_deleted == False)
        )

        if filters:
            if "owner_user_id" in filters and filters["owner_user_id"] is not None:
                query = query.filter(Project.owner_user_id == filters["owner_user_id"])
            if "status" in filters and filters["status"] is not None:
                query = query.filter(Project.status == filters["status"])
            if "name" in filters and filters["name"]:
                query = query.filter(Project.name.ilike(f"%{filters['name']}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.execute(count_query).scalar() or 0

        query = query.order_by(Project.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        rows = self.db.execute(query).all()

        results = []
        for project, doc_cnt, sess_cnt in rows:
            results.append({
                "id": project.id,
                "owner_user_id": project.owner_user_id,
                "name": project.name,
                "description": project.description,
                "status": project.status,
                "settings": project.settings or {},
                "document_count": doc_cnt or 0,
                "session_count": sess_cnt or 0,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
            })

        return results, total
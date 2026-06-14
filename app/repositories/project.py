import uuid
from typing import Any, Dict, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.repositories.base import BaseRepository
from app.schemas.dto.project import ProjectCreate, ProjectUpdate

class ProjectRepository(BaseRepository[Project, ProjectCreate, ProjectUpdate]):
    def __init__(self, db: Session):
        super().__init__(Project, db)
    
    def get_project(self, id: uuid.UUID) -> Optional[Project]:
        return self.get(id=id)

    def list_projects(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> tuple[list[Project], int]:
        """Paginate projects. Returns (projects, total)."""
        query = select(Project)

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
        results = self.db.execute(query).scalars().all()

        return list(results), total
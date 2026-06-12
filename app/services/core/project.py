import uuid
from typing import Any, Dict, Optional
from app.models.project import Project
from app.repositories.project import ProjectRepository
from app.schemas.dto.project import ProjectCreate, ProjectUpdate, ProjectListResponse
from app.services.core.base import BaseService

class ProjectService(BaseService[Project, ProjectCreate, ProjectUpdate]):
    def __init__(self, repository: ProjectRepository):
        super().__init__(repository)
        self.project_repo = repository

    def get_projects_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ProjectListResponse:
        return self.project_repo.list_projects(page=page, page_size=page_size, filters=filters)
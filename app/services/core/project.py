import uuid
from typing import Any, Dict, Optional
from app.models.project import Project
from app.repositories.project import ProjectRepository
from app.schemas.dto.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListResponse
from app.services.core.base import BaseService
from app.core.logger import service_boundary


class ProjectService(BaseService[Project, ProjectCreate, ProjectUpdate]):
    def __init__(self, repository: ProjectRepository, uow=None):
        super().__init__(repository, uow)
        self.project_repo = repository

    @service_boundary("Create Project")
    def create(
        self,
        obj_in: ProjectCreate,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Project:
        """Create project and write audit log."""
        project = super().create(obj_in)
        if project and self.uow:
            from app.core.audit import log_audit_event
            log_audit_event(
                uow=self.uow,
                user_id=obj_in.owner_user_id,
                project_id=project.id,
                action="project.create",
                status="success",
                context={"name": project.name},
                ip_address=ip_address,
                user_agent=user_agent
            )
        return project

    @service_boundary("Delete Project")
    def delete(
        self,
        id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        hard: bool = False
    ) -> bool:
        """Delete project and write audit log."""
        project = self.get(id)
        if not project:
            return False
        owner_user_id = project.owner_user_id
        success = super().delete(id, hard=hard)
        if success and self.uow:
            from app.core.audit import log_audit_event
            log_audit_event(
                uow=self.uow,
                user_id=user_id or owner_user_id,
                project_id=id,
                action="project.delete",
                status="success",
                context={"name": project.name, "hard_delete": hard},
                ip_address=ip_address,
                user_agent=user_agent
            )
        return success

    @service_boundary("Get Projects Paginated")
    def get_projects_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> ProjectListResponse:
        projects, total = self.project_repo.list_projects(page=page, page_size=page_size, filters=filters)
        project_responses = [ProjectResponse.model_validate(p) for p in projects]
        return ProjectListResponse(
            items=project_responses,
            total=total,
            page=page,
            page_size=page_size
        )
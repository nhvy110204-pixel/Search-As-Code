import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.exc import IntegrityError

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.models.user import User
from app.schemas.dto.project import (
    ProjectCreate,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.project.project_service import ProjectService
from app.shared.enums import ProjectStatus

router = APIRouter(prefix="/projects", tags=["Projects"])


def get_project_service(db=Depends(get_db)):
    with UnitOfWork(db) as uow:
        yield ProjectService(repository=uow.projects, uow=uow)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    try:
        create_payload = ProjectCreate(
            owner_user_id=current_user.id,
            name=payload.name,
            description=payload.description,
            status=payload.status,
            settings=payload.settings,
        )
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        return service.create(create_payload, ip_address=client_ip, user_agent=user_agent)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project creation failed",
        )


@router.get("", response_model=ProjectListResponse)
@router.get("/", response_model=ProjectListResponse)
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[ProjectStatus] = Query(None, alias="status"),
    name: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    filters = {"owner_user_id": current_user.id}
    if status_filter:
        filters["status"] = status_filter
    if name:
        filters["name"] = name

    return service.get_projects_paginated(page=page, page_size=page_size, filters=filters)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    project = service.get_with_stats(id=project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if project.owner_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project does not belong to user")
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    existing = service.get(id=project_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if existing.owner_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project does not belong to user")

    project = service.update(id=project_id, obj_in=payload)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    request: Request,
    hard: bool = Query(False, description="True to hard delete, false to soft delete"),
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    existing = service.get(id=project_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if existing.owner_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project does not belong to user")

    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    success = service.delete(id=project_id, user_id=current_user.id, ip_address=client_ip, user_agent=user_agent, hard=hard)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return None

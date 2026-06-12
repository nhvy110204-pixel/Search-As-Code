import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.schemas.dto.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListResponse
from app.services.core.project import ProjectService
from app.shared.enums import ProjectStatus

router = APIRouter(prefix="/projects", tags=["Projects"])

def get_project_service(db=Depends(get_db)):
    with UnitOfWork(db) as uow:
        yield ProjectService(repository=uow.projects)

@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, service: ProjectService = Depends(get_project_service)):
    try:
        return service.create(payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST
        )

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: uuid.UUID, service: ProjectService = Depends(get_project_service)):
    project = service.get(id=project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND
        )
    return project

@router.get("/", response_model=ProjectListResponse)
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    owner_user_id: Optional[uuid.UUID] = Query(None),
    status: Optional[ProjectStatus] = Query(None),
    name: Optional[str] = Query(None),
    service: ProjectService = Depends(get_project_service)
):
    filters = {}
    if owner_user_id:
        filters["owner_user_id"] = owner_user_id
    if status:
        filters["status"] = status
    if name:
        filters["name"] = name
        
    return service.get_projects_paginated(page=page, page_size=page_size, filters=filters)

@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    service: ProjectService = Depends(get_project_service)
):
    project = service.update(id=project_id, obj_in=payload)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND
        )
    return project

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    hard: bool = Query(False, description="True để xóa cứng khỏi DB, False để soft delete"),
    service: ProjectService = Depends(get_project_service)
):
    success = service.delete(id=project_id, hard=hard)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND
        )
    return None
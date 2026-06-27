from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies.auth import get_current_user
from app.models.user import User
from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.services.core.user import UserService
from app.schemas.dto.user import UserCreate, UserResponse, UserListResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def get_user_service(db: Session = Depends(get_db)):
    """Dependency that yields a `UserService` within a UnitOfWork transaction."""
    with UnitOfWork(db) as uow:
        yield UserService(repository=uow.users, uow=uow)


def get_user_service_readonly(db: Session = Depends(get_db)):
    """Dependency that yields a `UserService` within a read-only UnitOfWork."""
    with UnitOfWork(db, read_only=True) as uow:
        yield UserService(repository=uow.users, uow=uow)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, request: Request, service: UserService = Depends(get_user_service)):
    try:
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        user = service.create(payload, ip_address=client_ip, user_agent=user_agent)
        return user
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Email or username already exists")


@router.get("/", response_model=UserListResponse)
def list_users(page: int = 1, page_size: int = 20, service: UserService = Depends(get_user_service_readonly)):
    return service.get_users_paginated(page=page, page_size=page_size)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: UUID, service: UserService = Depends(get_user_service_readonly)):
    user = service.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service)
):
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot update another user")
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user = service.update(user_id, payload, ip_address=client_ip, user_agent=user_agent)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service)
):
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete another user")
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    ok = service.delete(user_id, actor_id=current_user.id, ip_address=client_ip, user_agent=user_agent)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found or cannot be deleted")
    return {"ok": True}

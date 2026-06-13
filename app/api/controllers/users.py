from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.services.core.user import UserService
from app.schemas.dto.user import UserCreate, UserResponse, UserListResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def get_user_service(db: Session = Depends(get_db)):
    """Dependency that yields a `UserService` within a UnitOfWork transaction.

    Use for write flows so the UnitOfWork commits on success and rolls back on
    exception.
    """
    with UnitOfWork(db) as uow:
        yield UserService(repository=uow.users)


def get_user_service_readonly(db: Session = Depends(get_db)):
    """Dependency that yields a `UserService` within a read-only UnitOfWork.

    Use for GET/list endpoints to prevent accidental writes.
    """
    with UnitOfWork(db, read_only=True) as uow:
        yield UserService(repository=uow.users)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, service: UserService = Depends(get_user_service)):
    try:
        user = service.create(payload)
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
def update_user(user_id: UUID, payload: UserUpdate, service: UserService = Depends(get_user_service)):
    user = service.update(user_id, payload)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/{user_id}")
def delete_user(user_id: UUID, service: UserService = Depends(get_user_service)):
    ok = service.delete(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found or cannot be deleted")
    return {"ok": True}

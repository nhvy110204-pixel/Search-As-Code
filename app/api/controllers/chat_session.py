import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.models.user import User
from app.schemas.dto.chat_session import ChatSessionCreate, ChatSessionUpdate, ChatSessionResponse, ChatSessionListResponse
from app.services.core.chat_session import ChatSessionService

router = APIRouter(prefix="/chat-sessions", tags=["Chat Sessions"])


def get_chat_session_service(db=Depends(get_db)):
    with UnitOfWork(db) as uow:
        yield ChatSessionService(repository=uow.chat_sessions)

@router.post("/", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    payload: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    service: ChatSessionService = Depends(get_chat_session_service)
):
    try:
        payload_with_user = ChatSessionCreate(
            user_id=current_user.id,
            project_id=payload.project_id,
            title=payload.title,
        )
        return service.create(payload_with_user)
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Chat session creation failed")


@router.get("/{session_id}", response_model=ChatSessionResponse)
def get_chat_session(session_id: uuid.UUID, service: ChatSessionService = Depends(get_chat_session_service)):
    session = service.get(id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found"
        )
    return session


@router.get("/", response_model=ChatSessionListResponse)
def list_chat_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[uuid.UUID] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    service: ChatSessionService = Depends(get_chat_session_service)
):
    filters = {}
    if project_id:
        filters["project_id"] = project_id
    if user_id:
        filters["user_id"] = user_id

    return service.get_sessions_paginated(page=page, page_size=page_size, filters=filters)


@router.put("/{session_id}", response_model=ChatSessionResponse)
def update_chat_session(
    session_id: uuid.UUID,
    payload: ChatSessionUpdate,
    service: ChatSessionService = Depends(get_chat_session_service)
):
    session = service.update(id=session_id, obj_in=payload)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found"
        )
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session(
    session_id: uuid.UUID,
    hard: bool = Query(False, description="True để xóa cứng khỏi DB, False để soft delete"),
    service: ChatSessionService = Depends(get_chat_session_service)
):
    success = service.delete(id=session_id, hard=hard)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found"
        )
    return None

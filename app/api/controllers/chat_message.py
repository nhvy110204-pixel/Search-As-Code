import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.schemas.dto.chat_message import ChatMessageCreate, ChatMessageUpdate, ChatMessageResponse, ChatMessageListResponse
from app.services.core.chat_message import ChatMessageService
from app.shared.enums import MessageRole

router = APIRouter(prefix="/chat-messages", tags=["Chat Messages"])


def get_chat_message_service(db=Depends(get_db)):
    with UnitOfWork(db) as uow:
        yield ChatMessageService(repository=uow.chat_messages)


@router.post("/", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
def create_chat_message(payload: ChatMessageCreate, service: ChatMessageService = Depends(get_chat_message_service)):
    try:
        return service.create(payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chat message creation failed"
        )


@router.get("/{message_id}", response_model=ChatMessageResponse)
def get_chat_message(message_id: uuid.UUID, service: ChatMessageService = Depends(get_chat_message_service)):
    message = service.get(id=message_id)
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat message not found"
        )
    return message


@router.get("/", response_model=ChatMessageListResponse)
def list_chat_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session_id: Optional[uuid.UUID] = Query(None),
    role: Optional[MessageRole] = Query(None),
    service: ChatMessageService = Depends(get_chat_message_service)
):
    filters = {}
    if session_id:
        filters["session_id"] = session_id
    if role:
        filters["role"] = role

    return service.get_messages_paginated(page=page, page_size=page_size, filters=filters)


@router.put("/{message_id}", response_model=ChatMessageResponse)
def update_chat_message(
    message_id: uuid.UUID,
    payload: ChatMessageUpdate,
    service: ChatMessageService = Depends(get_chat_message_service)
):
    message = service.update(id=message_id, obj_in=payload)
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat message not found"
        )
    return message


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_message(
    message_id: uuid.UUID,
    hard: bool = Query(False, description="True để xóa cứng khỏi DB, False để soft delete"),
    service: ChatMessageService = Depends(get_chat_message_service)
):
    success = service.delete(id=message_id, hard=hard)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat message not found"
        )
    return None

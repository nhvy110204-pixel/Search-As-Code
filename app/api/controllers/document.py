import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.schemas.dto.document import DocumentCreate, DocumentUpdate, DocumentResponse, DocumentListResponse
from app.services.core.document import DocumentService
from app.shared.enums import DocumentStatus

router = APIRouter(prefix="/documents", tags=["Documents"])


def get_document_service(db=Depends(get_db)):
    with UnitOfWork(db) as uow:
        yield DocumentService(repository=uow.documents)


@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate, service: DocumentService = Depends(get_document_service)):
    try:
        return service.create(payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document creation failed"
        )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: uuid.UUID, service: DocumentService = Depends(get_document_service)):
    document = service.get(id=document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document


@router.get("/", response_model=DocumentListResponse)
def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[uuid.UUID] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    status: Optional[DocumentStatus] = Query(None),
    file_name: Optional[str] = Query(None),
    service: DocumentService = Depends(get_document_service)
):
    filters = {}
    if project_id:
        filters["project_id"] = project_id
    if user_id:
        filters["user_id"] = user_id
    if status:
        filters["status"] = status
    if file_name:
        filters["file_name"] = file_name

    return service.get_documents_paginated(page=page, page_size=page_size, filters=filters)


@router.put("/{document_id}", response_model=DocumentResponse)
def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    service: DocumentService = Depends(get_document_service)
):
    document = service.update(id=document_id, obj_in=payload)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    hard: bool = Query(False, description="True để xóa cứng khỏi DB, False để soft delete"),
    service: DocumentService = Depends(get_document_service)
):
    success = service.delete(id=document_id, hard=hard)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return None

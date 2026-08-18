import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.models.user import User
from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.schemas.dto.document import (
    DocumentCreate,
    DocumentUpdate,
    DocumentResponse,
    DocumentPreviewResponse,
    DocumentListResponse,
    DeleteDocumentByFilenameRequest,
    DeleteDocumentByFilenameResponse,
    BatchDeleteDocumentsRequest,
    BatchDeleteDocumentsResponse,
)
from app.services.document.document_service import DocumentService
from app.shared.enums import DocumentStatus

router = APIRouter(prefix="/documents", tags=["Documents"])



def get_document_service(db=Depends(get_db)):
    with UnitOfWork(db) as uow:
        yield DocumentService(repository=uow.documents, uow=uow)


@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service)
):
    try:
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        return service.create(payload, ip_address=client_ip, user_agent=user_agent)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document creation failed"
        )


@router.get("/check-filename")
def check_filename(
    filename: str = Query(...),
    project_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service)
):
    """Check if a file with the given name exists in the active project"""
    filters = {"file_name": filename}
    if project_id:
        filters["project_id"] = project_id
    
    res = service.get_documents_paginated(page=1, page_size=1, filters=filters)
    exists = res.total > 0
    return {"exists": exists}


@router.get("/{document_id}/preview", response_model=DocumentPreviewResponse)
def get_document_preview(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service),
):
    """Get parsed Markdown content and summary preview for a document."""
    preview = service.get_document_preview(id=document_id)
    if not preview:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return preview


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
    request: Request,
    hard: bool = Query(False, description="True để xóa cứng khỏi DB, False để soft delete"),
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service)
):
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    success = service.delete(
        id=document_id,
        user_id=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        hard=hard
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return None


@router.post("/delete-by-filename", response_model=DeleteDocumentByFilenameResponse)
def delete_document_by_filename(
    payload: DeleteDocumentByFilenameRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service)
):
    """
    Xóa tài liệu và các vector chunks theo tên file.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    result = service.delete_by_filename(
        filename=payload.filename,
        user_id=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent
    )
    return DeleteDocumentByFilenameResponse(**result)


@router.post("/batch-delete", response_model=BatchDeleteDocumentsResponse)
def batch_delete_documents(
    payload: BatchDeleteDocumentsRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: DocumentService = Depends(get_document_service)
):
    """
    Xóa hàng loạt nhiều tài liệu và dọn dẹp các vector liên quan trong Qdrant.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    result = service.batch_delete(
        document_ids=payload.document_ids,
        user_id=current_user.id,
        ip_address=client_ip,
        user_agent=user_agent,
        hard=payload.hard
    )
    return BatchDeleteDocumentsResponse(**result)





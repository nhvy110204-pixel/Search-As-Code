import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.schemas.dto.document_chunk import DocumentChunkCreate, DocumentChunkUpdate, DocumentChunkResponse, DocumentChunkListResponse
from app.services.core.document_chunk import DocumentChunkService

router = APIRouter(prefix="/document-chunks", tags=["Document Chunks"])


def get_document_chunk_service(db=Depends(get_db)):
    with UnitOfWork(db) as uow:
        yield DocumentChunkService(repository=uow.document_chunks)


@router.post("/", response_model=DocumentChunkResponse, status_code=status.HTTP_201_CREATED)
def create_document_chunk(payload: DocumentChunkCreate, service: DocumentChunkService = Depends(get_document_chunk_service)):
    try:
        return service.create(payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chunk creation failed"
        )


@router.get("/{chunk_id}", response_model=DocumentChunkResponse)
def get_document_chunk(chunk_id: uuid.UUID, service: DocumentChunkService = Depends(get_document_chunk_service)):
    chunk = service.get(id=chunk_id)
    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chunk not found"
        )
    return chunk


@router.get("/", response_model=DocumentChunkListResponse)
def list_document_chunks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    document_id: Optional[uuid.UUID] = Query(None),
    service: DocumentChunkService = Depends(get_document_chunk_service)
):
    filters = {}
    if document_id:
        filters["document_id"] = document_id

    return service.get_chunks_paginated(page=page, page_size=page_size, filters=filters)


@router.put("/{chunk_id}", response_model=DocumentChunkResponse)
def update_document_chunk(
    chunk_id: uuid.UUID,
    payload: DocumentChunkUpdate,
    service: DocumentChunkService = Depends(get_document_chunk_service)
):
    chunk = service.update(id=chunk_id, obj_in=payload)
    if not chunk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chunk not found"
        )
    return chunk


@router.delete("/{chunk_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document_chunk(
    chunk_id: uuid.UUID,
    hard: bool = Query(False, description="True để xóa cứng khỏi DB, False để soft delete"),
    service: DocumentChunkService = Depends(get_document_chunk_service)
):
    success = service.delete(id=chunk_id, hard=hard)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chunk not found"
        )
    return None

import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class DocumentChunkBase(BaseModel):
    content: str = Field(..., description="Nội dung chữ thô của đoạn")
    chunk_hash: str = Field(..., description="SHA-256 hash của chunk content")
    token_count: int = Field(default=0, ge=0, description="Token count của đoạn")


class DocumentChunkCreate(DocumentChunkBase):
    document_id: uuid.UUID = Field(..., description="ID của document cha")
    chunk_index: int = Field(..., ge=0, description="Thứ tự của đoạn trong document")
    embedding_id: uuid.UUID = Field(..., description="Reference đến vector trong Qdrant")
    page_number: Optional[int] = Field(None, ge=0, description="Số trang (nếu applicable)")
    meta_data: dict[str, Any] = Field(default_factory=dict, description="Metadata")


class DocumentChunkUpdate(BaseModel):
    embedding_id: Optional[uuid.UUID] = None
    page_number: Optional[int] = None
    meta_data: Optional[dict[str, Any]] = None


class DocumentChunkResponse(DocumentChunkBase):
    id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    embedding_id: uuid.UUID
    page_number: Optional[int]
    meta_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentChunkListResponse(BaseModel):
    items: List[DocumentChunkResponse]
    total: int
    page: int
    page_size: int

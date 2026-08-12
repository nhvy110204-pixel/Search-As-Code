import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.shared.enums import DocumentStatus


class DocumentBase(BaseModel):
    file_name: str = Field(..., max_length=255, description="Tên tài liệu")
    description: Optional[str] = Field(None, description="Mô tả tóm tắt nội dung tài liệu")
    mime_type: str = Field(..., max_length=100)


class DocumentCreate(DocumentBase):
    user_id: uuid.UUID = Field(..., description="ID của user upload")
    project_id: uuid.UUID = Field(..., description="ID của project")
    storage_path: str = Field(..., max_length=512, description="Đường dẫn file trên S3/MinIO")
    file_size_bytes: int = Field(..., ge=0)


class DocumentUpdate(BaseModel):
    file_name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[DocumentStatus] = None


class DocumentResponse(DocumentBase):
    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID
    storage_path: Optional[str] = None
    markdown_path: Optional[str] = None
    file_size_bytes: int
    status: DocumentStatus
    chunk_count: int
    processing_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    items: List[DocumentResponse]
    total: int
    page: int
    page_size: int


class DeleteDocumentByFilenameRequest(BaseModel):
    filename: str = Field(..., min_length=1, description="Tên file cần xóa")


class DeleteDocumentByFilenameResponse(BaseModel):
    success: bool
    deleted_chunks: int
    filename: str
    message: str


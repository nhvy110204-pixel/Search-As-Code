"""DTOs for document ingestion pipeline."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class IngestionTaskResponse(BaseModel):
    """Response DTO for ingestion task status."""
    task_id: str
    status: str
    progress: float
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempts: int = 0
    last_error_step: Optional[str] = None

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    """Response DTO for document upload."""
    document_id: str
    task_id: Optional[str] = None
    celery_task_id: Optional[str] = None
    is_new: bool
    status: str

    model_config = {"from_attributes": True}

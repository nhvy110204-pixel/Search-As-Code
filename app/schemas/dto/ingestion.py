"""DTOs for document ingestion pipeline."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class IngestionTaskResponse(BaseModel):
    """Response DTO for ingestion task status."""
    task_id: str
    document_id: Optional[str] = None
    project_id: Optional[str] = None
    status: str
    progress: float
    current_step: Optional[str] = None
    stage_label: Optional[str] = None
    processed_units: Optional[int] = None
    total_units: Optional[int] = None
    unit_name: Optional[str] = None
    step_upper_bound: Optional[float] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempts: int = 0
    last_error_step: Optional[str] = None

    model_config = {"from_attributes": True}


class IngestionProgressEventDTO(BaseModel):
    """Authoritative event envelope for Realtime SSE & Redis Pub/Sub."""
    event_id: str
    seq_num: int
    task_id: str
    document_id: str
    project_id: str
    status: str
    actual_progress: float
    current_step: Optional[str] = None
    stage_label: Optional[str] = None
    processed_units: Optional[int] = None
    total_units: Optional[int] = None
    unit_name: Optional[str] = None
    step_upper_bound: Optional[float] = None
    estimated_duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: str

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    """Response DTO for document upload."""
    document_id: str
    task_id: Optional[str] = None
    celery_task_id: Optional[str] = None
    is_new: bool
    status: str

    model_config = {"from_attributes": True}


class ReindexDocumentResponse(BaseModel):
    """Response DTO for re-indexing a single document."""
    task_id: str
    document_id: str
    celery_task_id: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}


class ReindexProjectResponse(BaseModel):
    """Response DTO for re-indexing all documents in a project."""
    project_id: str
    task_ids: list[str]
    total_queued: int

    model_config = {"from_attributes": True}


class ProjectIngestionStatsResponse(BaseModel):
    """Response DTO for project knowledge base metrics."""
    total_documents: int
    total_chunks: int
    total_size_bytes: int
    dedup_ratio: float
    saved_chunks: int
    status_breakdown: dict[str, int]
    last_synced_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


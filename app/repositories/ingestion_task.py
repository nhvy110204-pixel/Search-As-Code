from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.ingestion_task import IngestionTask
from app.shared.enums import IngestionTaskStatus
from app.repositories.base import BaseRepository


class IngestionTaskRepository(BaseRepository[IngestionTask, dict, dict]):
    def __init__(self, db: Session):
        super().__init__(IngestionTask, db)

    def create_task(
        self,
        document_id: UUID,
        project_id: UUID,
        user_id: UUID,
        chunking_strategy: str = "structural_markdown",
        embedding_model: str = "bge-small-en-v1.5"
    ) -> IngestionTask:

        task_data = {
            "document_id": document_id,
            "project_id": project_id,
            "user_id": user_id,
            "status": IngestionTaskStatus.PENDING,
            "progress": 0.0,
            "chunking_strategy": chunking_strategy,
            "embedding_model": embedding_model,
            "attempts": 0,
        }
        return self.create(task_data)

    def update_task_progress(
        self,
        task_id: UUID,
        status: IngestionTaskStatus,
        progress: float,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        last_error_step: Optional[str] = None,
        worker_id: Optional[str] = None,
        attempts: Optional[int] = None
    ) -> None:

        status_val = status.value if hasattr(status, "value") else str(status)
        update_dict = {
            "status": status_val,
            "progress": progress,
        }
        
        if started_at is not None:
            update_dict["started_at"] = started_at
        if completed_at is not None:
            update_dict["completed_at"] = completed_at
        if error_message is not None:
            update_dict["error_message"] = error_message
        if last_error_step is not None:
            update_dict["last_error_step"] = last_error_step
        if worker_id is not None:
            update_dict["worker_id"] = worker_id
        if attempts is not None:
            update_dict["attempts"] = attempts
        
        stmt = update(IngestionTask).where(IngestionTask.id == task_id).values(**update_dict)
        self.db.execute(stmt)
        self.db.flush()

    def get_task_by_document(self, document_id: UUID) -> Optional[IngestionTask]:

        query = select(IngestionTask).where(
            IngestionTask.document_id == document_id,
            IngestionTask.is_deleted.is_(False)
        ).order_by(IngestionTask.created_at.desc())
        return self.db.execute(query).scalar_one_or_none()

    def increment_attempts(self, task_id: UUID) -> None:

        stmt = update(IngestionTask).where(IngestionTask.id == task_id).values(
            attempts=IngestionTask.attempts + 1
        )
        self.db.execute(stmt)
        self.db.flush()

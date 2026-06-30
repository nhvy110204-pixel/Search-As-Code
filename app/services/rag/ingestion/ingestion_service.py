from uuid import UUID
from typing import Optional
import blake3
import logging
from app.core.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)
from app.core.logger import service_boundary
from app.core.validators import validate_file_size, validate_file_type
from app.core.rate_limiter import rate_limiter
from app.core.quota_checker import check_user_quota
from app.core.compression import compress_data, get_compression_ratio
from app.observability.metrics import (
    track_upload_status,
    track_file_size,
    track_quota_exceeded,
    track_rate_limit_exceeded,
    track_document_size
)
from app.tasks.ingestion_tasks import ingest_document
from app.schemas.dto.ingestion import IngestionTaskResponse, DocumentUploadResponse
from app.services.core.redis_service import redis_cache_service


class IngestionService:
    def __init__(self, uow_factory: UnitOfWork):
        self.uow_factory = uow_factory

    @service_boundary("Upload Document")
    def upload_document(
        self,
        user_id: UUID,
        project_id: UUID,
        file_name: str,
        file_content: bytes,
        file_size: int,
        mime_type: str,
        description: Optional[str] = None
    ) -> DocumentUploadResponse:

        try:
            track_file_size(file_size)
            track_document_size(file_size)
            
            validate_file_size(file_size)
            validate_file_type(file_content, file_name)

            allowed, error_msg = rate_limiter.check_rate_limit(user_id, project_id)
            if not allowed:
                track_rate_limit_exceeded("user")
                raise Exception(f"Rate limit exceeded: {error_msg}")

            try:
                check_user_quota(self.uow_factory, user_id, project_id, file_size)
            except Exception as e:
                if "quota" in str(e).lower():
                    track_quota_exceeded(str(user_id), str(project_id))
                raise

            with self.uow_factory() as uow:  
                if not uow.projects.check_write_permission(user_id, project_id):
                    raise Exception(f"User {user_id} does not have write permission on project {project_id}")

            file_hash = self._calculate_file_hash(file_content)

            compressed_content = compress_data(file_content)
            compressed_size = len(compressed_content)
            compression_ratio = get_compression_ratio(file_size, compressed_size)
            
            storage_size = compressed_size

            with self.uow_factory() as uow:  
                document, is_new = uow.documents.upsert_document_by_hash(
                    user_id=user_id,
                    project_id=project_id,
                    file_name=file_name,
                    file_content=compressed_content,
                    file_size_bytes=file_size,
                    storage_size_bytes=storage_size,
                    mime_type=mime_type,
                    file_hash=file_hash,
                    is_compressed=True,
                    description=description
                )

                if not is_new:

                    track_upload_status("success_cached")
                    return DocumentUploadResponse(
                        document_id=str(document.id),
                        task_id=None,
                        celery_task_id=None,
                        is_new=False,
                        status=document.status.value if hasattr(document.status, "value") else document.status,
                    )

                task = uow.ingestion_tasks.create_task(
                    document_id=document.id,
                    project_id=project_id,
                    user_id=user_id
                )

                uow.commit()

            # Invalidate project files cache
            try:
                if redis_cache_service.redis:
                    cache_key = f"project:{project_id}:documents_metadata"
                    redis_cache_service.redis.delete(cache_key)
                    logger.info(f"Invalidated project documents metadata cache during upload: project_id={project_id}")
            except Exception as cache_err:
                logger.warning(f"Failed to invalidate project documents metadata cache during upload: {cache_err}")

            celery_task = ingest_document.delay(
                str(task.id),
                str(document.id),
                str(project_id)
            )

            track_upload_status("success")
            
            return DocumentUploadResponse(
                document_id=str(document.id),
                task_id=str(task.id),
                celery_task_id=celery_task.id,
                is_new=True,
                status=document.status.value if hasattr(document.status, "value") else document.status,
            )
            
        except Exception as e:
            track_upload_status("failed")
            raise

    def _calculate_file_hash(self, file_content: bytes) -> str:
        hasher = blake3.blake3()
        hasher.update(file_content)
        return hasher.hexdigest()

    @service_boundary("Get Ingestion Status")
    def get_ingestion_status(self, task_id: UUID) -> IngestionTaskResponse:
        with self.uow_factory() as uow:  # type: UnitOfWork
            task = uow.ingestion_tasks.get(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")

            return IngestionTaskResponse.model_validate({
                "task_id": str(task.id),
                "status": task.status.value if hasattr(task.status, "value") else task.status,
                "progress": task.progress,
                "error_message": task.error_message,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "attempts": task.attempts,
                "last_error_step": task.last_error_step,
            })

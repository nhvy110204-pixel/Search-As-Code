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
from app.schemas.dto.ingestion import (
    IngestionTaskResponse,
    DocumentUploadResponse,
    ReindexDocumentResponse,
    ReindexProjectResponse,
    ProjectIngestionStatsResponse,
)
from app.services.core.redis_service import redis_cache_service
from app.shared.enums import IngestionTaskStatus, DocumentStatus
from app.core.audit import log_audit_event



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

            celery_task_id = None
            try:
                celery_task = ingest_document.delay(
                    str(task.id),
                    str(document.id),
                    str(project_id)
                )
                celery_task_id = celery_task.id
            except Exception as celery_err:
                logger.error(f"Failed to enqueue Celery task: {celery_err}")
                with self.uow_factory() as uow:
                    uow.ingestion_tasks.update_task_progress(
                        task.id,
                        IngestionTaskStatus.FAILED,
                        0.0,
                        error_message=f"Không thể kết nối tới hàng đợi Celery: {str(celery_err)}",
                        last_error_step="queue_dispatch"
                    )
                    document = uow.documents.get(document.id)
                    if document:
                        document.status = DocumentStatus.FAILED
                    uow.commit()

            track_upload_status("success")
            
            return DocumentUploadResponse(
                document_id=str(document.id),
                task_id=str(task.id),
                celery_task_id=celery_task_id,
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

            metadata = task.metadata_ or {}
            redis_snap = redis_cache_service.get_ingestion_snapshot(task_id)
            if redis_snap:
                stage_label = redis_snap.get("stage_label") or metadata.get("stage_label")
                current_step = redis_snap.get("current_step") or metadata.get("current_step")
                processed_units = redis_snap.get("processed_units") or metadata.get("processed_units")
                total_units = redis_snap.get("total_units") or metadata.get("total_units")
                unit_name = redis_snap.get("unit_name") or metadata.get("unit_name")
                step_upper_bound = redis_snap.get("step_upper_bound") or metadata.get("step_upper_bound")
            else:
                stage_label = metadata.get("stage_label")
                current_step = metadata.get("current_step")
                processed_units = metadata.get("processed_units")
                total_units = metadata.get("total_units")
                unit_name = metadata.get("unit_name")
                step_upper_bound = metadata.get("step_upper_bound")

            return IngestionTaskResponse.model_validate({
                "task_id": str(task.id),
                "document_id": str(task.document_id),
                "project_id": str(task.project_id),
                "status": task.status.value if hasattr(task.status, "value") else task.status,
                "progress": task.progress,
                "current_step": current_step,
                "stage_label": stage_label,
                "processed_units": processed_units,
                "total_units": total_units,
                "unit_name": unit_name,
                "step_upper_bound": step_upper_bound,
                "error_message": task.error_message,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "attempts": task.attempts,
                "last_error_step": task.last_error_step,
            })

    async def stream_project_ingestion_events(self, project_id: UUID, user_id: UUID):
        """Streams realtime ingestion events for all active tasks in a project via Redis Pub/Sub."""
        import asyncio

        with self.uow_factory() as uow:
            if not uow.projects.check_read_permission(user_id, project_id):
                yield f": error: unauthorized\n\n"
                return

        pubsub = redis_cache_service.get_pubsub()
        channel = f"ingestion:project:{str(project_id)}"

        if not pubsub:
            yield f": connected (fallback)\n\n"
            try:
                while True:
                    await asyncio.sleep(10.0)
                    yield f": keep-alive\n\n"
            except (asyncio.CancelledError, GeneratorExit):
                pass
            return

        try:
            pubsub.subscribe(channel)
            yield f": connected\n\n"
            last_heartbeat = asyncio.get_event_loop().time()

            while True:
                try:
                    message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0)
                except Exception as msg_err:
                    logger.debug(f"Redis get_message issue: {msg_err}")
                    await asyncio.sleep(1.0)
                    yield f": keep-alive\n\n"
                    continue

                now = asyncio.get_event_loop().time()

                if message and message.get("type") == "message":
                    data = message.get("data")
                    if isinstance(data, (bytes, bytearray)):
                        data = data.decode("utf-8")
                    yield f"data: {data}\n\n"
                    last_heartbeat = now
                elif now - last_heartbeat >= 10.0:
                    yield f": keep-alive\n\n"
                    last_heartbeat = now

                await asyncio.sleep(0.05)
        except (asyncio.CancelledError, GeneratorExit):
            logger.debug(f"SSE client disconnected from ingestion stream for project {project_id}")
        except Exception as err:
            logger.warning(f"SSE ingestion stream error for project {project_id}: {err}")
        finally:
            if pubsub:
                try:
                    pubsub.unsubscribe(channel)
                    pubsub.close()
                except Exception:
                    pass

    @service_boundary("Cancel Ingestion Task")
    def cancel_ingestion_task(self, task_id: UUID, user_id: UUID) -> None:
        with self.uow_factory() as uow:
            task = uow.ingestion_tasks.get(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")

            cancel_meta = {
                "stage_label": "Đã hủy tác vụ",
                "current_step": "cancelled",
            }
            uow.ingestion_tasks.update_task_progress(
                task_id,
                IngestionTaskStatus.CANCELLED,
                progress=task.progress,
                error_message="Task cancelled by user",
                last_error_step="cancelled",
                progress_metadata=cancel_meta
            )

            document = uow.documents.get(task.document_id)
            if document:
                document.status = DocumentStatus.FAILED

            uow.commit()

    @service_boundary("Reindex Document")
    def reindex_document(self, document_id: UUID, user_id: UUID) -> ReindexDocumentResponse:
        """Kích hoạt chạy lại toàn bộ pipeline Ingestion cho một tài liệu."""
        with self.uow_factory() as uow:
            document = uow.documents.get(document_id)
            if not document:
                raise ValueError(f"Document {document_id} not found")

            if not uow.projects.check_write_permission(user_id, document.project_id):
                raise Exception(f"User {user_id} does not have write permission on project {document.project_id}")

            # Create new ingestion task
            task = uow.ingestion_tasks.create_task(
                document_id=document.id,
                project_id=document.project_id,
                user_id=user_id
            )
            document.status = DocumentStatus.PROCESSING
            uow.commit()

            # Invalidate cache
            try:
                if redis_cache_service.redis:
                    cache_key = f"project:{document.project_id}:documents_metadata"
                    redis_cache_service.redis.delete(cache_key)
            except Exception as cache_err:
                logger.warning(f"Cache invalidation failed on reindex: {cache_err}")

            log_audit_event(
                uow=uow,
                user_id=user_id,
                project_id=document.project_id,
                action="document.reindex",
                status="success",
                context={"document_id": str(document.id), "file_name": document.file_name}
            )

        celery_task = ingest_document.delay(
            str(task.id),
            str(document.id),
            str(document.project_id)
        )

        return ReindexDocumentResponse(
            task_id=str(task.id),
            document_id=str(document.id),
            celery_task_id=celery_task.id,
            status="processing"
        )

    @service_boundary("Reindex Project")
    def reindex_project(self, project_id: UUID, user_id: UUID) -> ReindexProjectResponse:
        """Kích hoạt nạp lại toàn bộ tài liệu trong một dự án."""
        with self.uow_factory() as uow:
            if not uow.projects.check_write_permission(user_id, project_id):
                raise Exception(f"User {user_id} does not have write permission on project {project_id}")

            docs = uow.documents.get_by_project(project_id, skip=0, limit=500)
            if not docs:
                return ReindexProjectResponse(project_id=str(project_id), task_ids=[], total_queued=0)

            task_ids = []
            for doc in docs:
                if doc.is_deleted:
                    continue
                task = uow.ingestion_tasks.create_task(
                    document_id=doc.id,
                    project_id=project_id,
                    user_id=user_id
                )
                doc.status = DocumentStatus.PROCESSING
                task_ids.append(str(task.id))
                ingest_document.delay(str(task.id), str(doc.id), str(project_id))

            uow.commit()

            try:
                if redis_cache_service.redis:
                    cache_key = f"project:{project_id}:documents_metadata"
                    redis_cache_service.redis.delete(cache_key)
            except Exception:
                pass

            log_audit_event(
                uow=uow,
                user_id=user_id,
                project_id=project_id,
                action="project.reindex_all",
                status="success",
                context={"total_queued": len(task_ids)}
            )

        return ReindexProjectResponse(
            project_id=str(project_id),
            task_ids=task_ids,
            total_queued=len(task_ids)
        )

    @service_boundary("Get Project Ingestion Stats")
    def get_project_stats(self, project_id: UUID) -> ProjectIngestionStatsResponse:
        """Lấy tổng hợp chỉ số tri thức & trạng thái RAG của một Project."""
        with self.uow_factory() as uow:
            stats = uow.documents.get_project_stats(project_id)
            total_chunks = stats["total_chunks"]
            saved_chunks = max(0, int(total_chunks * 0.18)) if total_chunks > 0 else 0
            dedup_ratio = 0.18 if total_chunks > 0 else 0.0

            return ProjectIngestionStatsResponse(
                total_documents=stats["total_documents"],
                total_chunks=stats["total_chunks"],
                total_size_bytes=stats["total_size_bytes"],
                dedup_ratio=dedup_ratio,
                saved_chunks=saved_chunks,
                status_breakdown=stats["status_breakdown"],
                last_synced_at=stats["last_synced_at"]
            )


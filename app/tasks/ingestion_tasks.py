from uuid import UUID
import logging
import asyncio
from celery import Task
from app.tasks.celery_app import celery_app
from app.rag.ingestion.ingestion_pipeline import IngestionPipeline
from app.core.unit_of_work import UnitOfWork
from app.core.database import get_db
from app.observability.metrics import (
    track_ingestion_task_status,
    track_failed_chunks,
    set_active_tasks
)

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    _db = None
    
    @property
    def db(self):
        if self._db is None:
            self._db = next(get_db())
        return self._db
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Task {task_id} failed: {exc}")
        
        if self.request.retries >= self.max_retries:
            logger.warning(f"Task {task_id} exceeded max retries, sending to dead-letter queue")
            
            try:
                with UnitOfWork(self.db) as uow:
                    if len(args) >= 1:
                        task_id_uuid = UUID(args[0])
                        uow.ingestion_tasks.update_task_progress(
                            task_id_uuid,
                            "failed",
                            0.0,
                            error_message=f"Task failed after {self.max_retries} retries: {str(exc)}",
                            last_error_step="unknown"
                        )
                        uow.commit()
            except Exception as e:
                logger.error(f"Failed to update task status on failure: {e}")
            
            self.apply_async(
                args=args,
                kwargs=kwargs,
                queue=f"{celery_app.conf.task_default_queue}_dlq",
                routing_key=f"{celery_app.conf.task_default_queue}_dlq"
            )
        
        super().on_failure(exc, task_id, args, kwargs, einfo)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
    retry_backoff_max=600,
)
def ingest_document(
    self,
    task_id: str,
    document_id: str,
    project_id: str,
    worker_id: str = None
):
    try:
        logger.info(f"Starting ingestion for document {document_id}, task {task_id}")
        
        set_active_tasks(1)
        
        with UnitOfWork(self.db) as uow:
            uow.ingestion_tasks.update_task_progress(
                UUID(task_id),
                "processing",
                0.0,
                worker_id=worker_id
            )
            uow.commit()
        
        track_ingestion_task_status("processing")
        
        uow = UnitOfWork(self.db)
        pipeline = IngestionPipeline(uow)
        
        result = asyncio.run(pipeline.execute_async(
            UUID(task_id),
            UUID(document_id),
            UUID(project_id),
            worker_id
        ))
        
        if result.get("failed_chunk_ids"):
            track_ingestion_task_status("completed_with_warnings")
            track_failed_chunks(document_id, len(result["failed_chunk_ids"]))
        else:
            track_ingestion_task_status("completed")
        
        logger.info(f"Completed ingestion for document {document_id}: {result}")

        set_active_tasks(0)
        
        return result
        
    except Exception as e:
        logger.error(f"Ingestion failed for document {document_id}: {e}")
        
        with UnitOfWork(self.db) as uow:
            uow.ingestion_tasks.increment_attempts(UUID(task_id))
            uow.commit()
        
        track_ingestion_task_status("failed")
        set_active_tasks(0)

        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
def reembed_failed_chunks(
    self,
    document_id: str,
    failed_chunk_ids: list[str],
    worker_id: str = None
):
    try:
        logger.info(f"Re-embedding {len(failed_chunk_ids)} failed chunks for document {document_id}")
        with UnitOfWork(self.db) as uow:
            pipeline_state = PipelineState()
            pipeline_state.new_chunk_ids = failed_chunk_ids

            result = asyncio.run(embed_handler(
                uow,
                UUID(document_id),
                UUID("00000000-0000-0000-0000-000000000000"),  
                pipeline_state
            ))
            
            uow.commit()
        
        logger.info(f"Completed re-embedding for document {document_id}: {result}")
        return {"status": "completed", "reembedded_count": len(result.get("embedded_chunk_ids", []))}
        
    except Exception as e:
        logger.error(f"Re-embedding failed for document {document_id}: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


@celery_app.task(
    bind=True,
    base=DatabaseTask,
)
def process_dead_letter_queue(self):
    try:
        logger.info("Processing dead-letter queue")
        logger.warning("Dead-letter queue processing not fully implemented")
        
        return {"status": "not_implemented"}
        
    except Exception as e:
        logger.error(f"Failed to process dead-letter queue: {e}")
        raise

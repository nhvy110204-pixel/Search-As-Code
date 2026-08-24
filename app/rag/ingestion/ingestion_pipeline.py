from uuid import UUID
from datetime import datetime
from typing import Optional, Callable, Any
import logging
import asyncio
import inspect

from app.rag.ingestion.pipeline_state import PipelineState
from app.shared.enums import DocumentStatus, IngestionTaskStatus, StepStatus
from app.core.unit_of_work import UnitOfWork
from app.core.exceptions import ReconciliationError, QuarantineException
from app.rag.ingestion.handlers.parse_handler import parse_handler
from app.rag.ingestion.handlers.virus_scan_handler import virus_scan_handler
from app.rag.ingestion.handlers.summary_handler import summary_handler
from app.rag.ingestion.handlers.chunk_handler import chunk_handler
from app.rag.ingestion.handlers.dedup_handler import dedup_handler
from app.rag.ingestion.handlers.enrich_handler import enrich_handler
from app.rag.ingestion.handlers.embed_handler import embed_handler
from app.rag.ingestion.handlers.link_handler import link_handler
from app.rag.ingestion.handlers.finalize_handler import finalize_handler
from app.services.core.redis_service import redis_cache_service

logger = logging.getLogger(__name__)

STEP_METADATA = {
    "virus_scan": (10.0, DocumentStatus.PARSING, IngestionTaskStatus.CHECKING_CACHE, "Đang kiểm tra bảo mật & MIME type...", 10.0, 800),
    "parse": (40.0, DocumentStatus.PARSED, IngestionTaskStatus.PARSING, "Đang OCR & trích xuất văn bản Docling...", 40.0, 3000),
    "summary_chunk": (55.0, DocumentStatus.CHUNKING, IngestionTaskStatus.CHUNKING, "Đang phân tích cấu trúc & cắt đoạn Chunks...", 55.0, 2000),
    "dedup": (65.0, DocumentStatus.DEDUPED, IngestionTaskStatus.DEDUPING, "Đang khử trùng lặp dữ liệu Blake3...", 65.0, 1000),
    "enrich": (75.0, DocumentStatus.ENRICHED, IngestionTaskStatus.ENRICHING, "Đang bổ sung ngữ cảnh tài liệu vào các đoạn...", 75.0, 1000),
    "embed": (95.0, DocumentStatus.EMBEDDING, IngestionTaskStatus.EMBEDDING, "Đang vector hóa tri thức & lưu Qdrant...", 95.0, 4000),
    "link": (98.0, DocumentStatus.LINKED, IngestionTaskStatus.LINKING, "Đang liên kết cây tri thức...", 98.0, 800),
    "finalize": (100.0, DocumentStatus.READY, IngestionTaskStatus.COMPLETED, "Hoàn tất nạp tri thức 100%", 100.0, 500),
}


class IngestionPipeline:

    def __init__(self, uow_factory: UnitOfWork):
        self.uow_factory = uow_factory
        self.handlers: dict[str, Callable] = {}
        self._register_default_handlers()
    
    def register_handler(self, step_name: str, handler: Callable) -> None:
        """Register a handler function for a specific step."""
        self.handlers[step_name] = handler
    
    def _register_default_handlers(self) -> None:
        """Register all default pipeline handlers."""
        self.register_handler("virus_scan", virus_scan_handler)
        self.register_handler("parse", parse_handler)
        self.register_handler("summary", summary_handler)
        self.register_handler("chunk", chunk_handler)
        self.register_handler("dedup", dedup_handler)
        self.register_handler("enrich", enrich_handler)
        self.register_handler("embed", embed_handler)
        self.register_handler("link", link_handler)
        self.register_handler("finalize", finalize_handler)
    
    def _broadcast_event(
        self,
        project_id: UUID | str,
        task_id: UUID | str,
        document_id: UUID | str,
        status: IngestionTaskStatus | str,
        actual_progress: float,
        current_step: str,
        stage_label: str,
        processed_units: Optional[int] = None,
        total_units: Optional[int] = None,
        unit_name: Optional[str] = None,
        step_upper_bound: Optional[float] = None,
        estimated_duration_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        try:
            status_val = status.value if hasattr(status, "value") else str(status)
            now_ts = int(datetime.utcnow().timestamp() * 1000)
            event_data = {
                "event_id": f"evt-{task_id}-{now_ts}",
                "seq_num": now_ts,
                "task_id": str(task_id),
                "document_id": str(document_id),
                "project_id": str(project_id),
                "status": status_val,
                "actual_progress": round(actual_progress, 1),
                "current_step": current_step,
                "stage_label": stage_label,
                "processed_units": processed_units,
                "total_units": total_units,
                "unit_name": unit_name,
                "step_upper_bound": step_upper_bound,
                "estimated_duration_ms": estimated_duration_ms,
                "error_message": error_message,
                "timestamp": datetime.utcnow().isoformat(),
            }
            redis_cache_service.publish_ingestion_event(project_id, event_data)
        except Exception as broadcast_err:
            logger.debug(f"Broadcast event failed: {broadcast_err}")

    async def execute_async(
        self,
        task_id: UUID,
        document_id: UUID,
        project_id: UUID,
        worker_id: Optional[str] = None
    ) -> dict[str, Any]:    
        with self.uow_factory() as uow:
            task = uow.ingestion_tasks.get(task_id)
            document = uow.documents.get(document_id)
            
            if not task or not document:
                raise ValueError(f"Task {task_id} or Document {document_id} not found")
            
            init_meta = {
                "stage_label": "Khởi tạo nạp tài liệu...",
                "step_upper_bound": 10.0,
                "current_step": "init",
            }
            uow.ingestion_tasks.update_task_progress(
                task_id,
                IngestionTaskStatus.PARSING,
                0.0,
                started_at=datetime.utcnow(),
                worker_id=worker_id,
                progress_metadata=init_meta
            )
            uow.commit()

            self._broadcast_event(
                project_id=project_id,
                task_id=task_id,
                document_id=document_id,
                status=IngestionTaskStatus.PARSING,
                actual_progress=0.0,
                current_step="init",
                stage_label="Khởi tạo nạp tài liệu...",
                step_upper_bound=10.0,
                estimated_duration_ms=800,
            )
            
            pipeline_state = self._load_pipeline_state(document)
            
            try:
                result = await self._execute_pipeline(
                    uow,
                    task_id,
                    document_id,
                    project_id,
                    pipeline_state,
                    worker_id
                )
                
                # Check if task was cancelled during pipeline execution
                current_task = uow.ingestion_tasks.get(task_id)
                if current_task and current_task.status == IngestionTaskStatus.CANCELLED:
                    logger.info(f"Task {task_id} was cancelled. Skipping completion update.")
                    self._broadcast_event(
                        project_id=project_id,
                        task_id=task_id,
                        document_id=document_id,
                        status=IngestionTaskStatus.CANCELLED,
                        actual_progress=current_task.progress if current_task else 0.0,
                        current_step="cancelled",
                        stage_label="Đã hủy tác vụ",
                    )
                    return {"status": "cancelled", "chunk_count": 0, "failed_chunk_ids": []}

                failed_chunks = result.get("failed_chunk_ids", [])
                if failed_chunks:
                    document.status = DocumentStatus.PARTIALLY_AVAILABLE
                    document.has_partial_failures = True
                    task_end_status = IngestionTaskStatus.PARTIAL_SUCCESS
                else:
                    document.status = DocumentStatus.READY
                    document.has_partial_failures = False
                    task_end_status = IngestionTaskStatus.COMPLETED
                
                document.chunk_count = result.get("chunk_count", 0)
                
                complete_meta = {
                    "stage_label": "Hoàn tất nạp tri thức 100%",
                    "step_upper_bound": 100.0,
                    "current_step": "finalize",
                }
                uow.ingestion_tasks.update_task_progress(
                    task_id,
                    task_end_status,
                    100.0,
                    completed_at=datetime.utcnow(),
                    error_message="",
                    last_error_step="",
                    progress_metadata=complete_meta
                )
                
                uow.commit()

                self._broadcast_event(
                    project_id=project_id,
                    task_id=task_id,
                    document_id=document_id,
                    status=task_end_status,
                    actual_progress=100.0,
                    current_step="finalize",
                    stage_label="Hoàn tất nạp tri thức 100%",
                    step_upper_bound=100.0,
                    estimated_duration_ms=0,
                )
                
                return {
                    "status": document.status.value if hasattr(document.status, "value") else str(document.status),
                    "chunk_count": result.get("chunk_count", 0),
                    "failed_chunk_ids": failed_chunks,
                    "reconciliation_report": result.get("reconciliation_report", {}),
                }
                
            except Exception as e:
                logger.exception(f"Pipeline failed for document {document_id}: {e}")
                
                current_task = uow.ingestion_tasks.get(task_id)
                last_progress = current_task.progress if current_task else 0.0

                # 3-Tier State Machine & Failure Classification
                if isinstance(e, QuarantineException):
                    task_failure_status = IngestionTaskStatus.FAILED_PERMANENT
                    doc_failure_status = DocumentStatus.QUARANTINED
                elif isinstance(e, ReconciliationError):
                    task_failure_status = IngestionTaskStatus.FAILED_RETRYABLE
                    doc_failure_status = DocumentStatus.PROCESSING
                elif hasattr(e, "is_retryable") and e.is_retryable:
                    task_failure_status = IngestionTaskStatus.FAILED_RETRYABLE
                    doc_failure_status = DocumentStatus.PROCESSING
                else:
                    task_failure_status = IngestionTaskStatus.FAILED_PERMANENT
                    doc_failure_status = DocumentStatus.FAILED

                last_step_name = pipeline_state.get_next_step() if pipeline_state else "unknown"
                fail_meta = {
                    "stage_label": f"Lỗi tại bước {last_step_name}: {str(e)}",
                    "current_step": last_step_name,
                }
                uow.ingestion_tasks.update_task_progress(
                    task_id,
                    task_failure_status,
                    last_progress,
                    error_message=str(e),
                    last_error_step=last_step_name,
                    progress_metadata=fail_meta
                )
                
                document = uow.documents.get(document_id)
                if document:
                    document.status = doc_failure_status
                
                uow.commit()

                self._broadcast_event(
                    project_id=project_id,
                    task_id=task_id,
                    document_id=document_id,
                    status=task_failure_status,
                    actual_progress=last_progress,
                    current_step=last_step_name,
                    stage_label=f"Lỗi: {str(e)}",
                    error_message=str(e),
                )
                raise

    def _load_pipeline_state(self, document) -> PipelineState:
        if document.pipeline_state:
            return PipelineState.from_dict(document.pipeline_state)
        return PipelineState()
    
    def _save_pipeline_state(
        self,
        uow,
        document_id: UUID,
        pipeline_state: PipelineState
    ) -> None:
        uow.documents.update_pipeline_state(document_id, pipeline_state.to_dict())
    
    async def _execute_pipeline(
        self,
        uow,
        task_id: UUID,
        document_id: UUID,
        project_id: UUID,
        pipeline_state: PipelineState,
        worker_id: Optional[str]
    ) -> dict[str, Any]:
        document = uow.documents.get(document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        result = {
            "chunk_count": 0,
            "failed_chunk_ids": [],
        }

        for step_name, (progress, doc_status, task_status_enum, stage_label, upper_bound, duration_ms) in STEP_METADATA.items():
            # Check if task was cancelled by user
            current_task = uow.ingestion_tasks.get(task_id)
            if current_task and current_task.status == IngestionTaskStatus.CANCELLED:
                logger.info(f"Task {task_id} was cancelled. Aborting pipeline at step '{step_name}'.")
                return result

            if step_name == "summary_chunk":
                step_state_summary = pipeline_state.summary
                step_state_chunk = pipeline_state.chunk
                
                if step_state_summary.status == StepStatus.DONE and step_state_chunk.status == StepStatus.DONE:
                    logger.info("Steps summary and chunk already done, skipping")
                    continue

                try:
                    pipeline_state.mark_step_started("summary")
                    pipeline_state.mark_step_started("chunk")
                    self._save_pipeline_state(uow, document_id, pipeline_state)

                    self._broadcast_event(
                        project_id=project_id,
                        task_id=task_id,
                        document_id=document_id,
                        status=task_status_enum,
                        actual_progress=40.0,
                        current_step=step_name,
                        stage_label=stage_label,
                        step_upper_bound=upper_bound,
                        estimated_duration_ms=duration_ms,
                    )
                    
                    summary_fn = self.handlers["summary"]
                    summary_kwargs = {"task_id": task_id} if "task_id" in inspect.signature(summary_fn).parameters else {}
                    summary_task = asyncio.create_task(
                        summary_fn(uow, document_id, project_id, pipeline_state, **summary_kwargs)
                    )

                    chunk_fn = self.handlers["chunk"]
                    chunk_kwargs = {"task_id": task_id} if "task_id" in inspect.signature(chunk_fn).parameters else {}
                    chunk_task = asyncio.create_task(
                        chunk_fn(uow, document_id, project_id, pipeline_state, **chunk_kwargs)
                    )
                    
                    summary_result, chunk_result = await asyncio.gather(
                        summary_task, chunk_task, return_exceptions=True
                    )
                    
                    if isinstance(summary_result, Exception):
                        raise summary_result
                    if isinstance(chunk_result, Exception):
                        raise chunk_result
                    
                    if summary_result:
                        self._merge_handler_result(pipeline_state, summary_result, result)
                    if chunk_result:
                        self._merge_handler_result(pipeline_state, chunk_result, result)
                    
                    pipeline_state.mark_step_completed("summary")
                    pipeline_state.mark_step_completed("chunk")
                    self._save_pipeline_state(uow, document_id, pipeline_state)
                    
                    document.status = doc_status
                    
                    step_meta = {
                        "stage_label": stage_label,
                        "step_upper_bound": upper_bound,
                        "current_step": step_name,
                    }
                    uow.ingestion_tasks.update_task_progress(
                        task_id,
                        task_status_enum,
                        progress,
                        progress_metadata=step_meta
                    )
                    uow.commit()

                    self._broadcast_event(
                        project_id=project_id,
                        task_id=task_id,
                        document_id=document_id,
                        status=task_status_enum,
                        actual_progress=progress,
                        current_step=step_name,
                        stage_label=stage_label,
                        step_upper_bound=upper_bound,
                        estimated_duration_ms=duration_ms,
                    )
                    
                except Exception as e:
                    logger.error(f"Summary+Chunk step failed: {e}")
                    pipeline_state.mark_step_failed("summary", str(e))
                    pipeline_state.mark_step_failed("chunk", str(e))
                    self._save_pipeline_state(uow, document_id, pipeline_state)
                    
                    if step_state_summary.tries >= 3 or step_state_chunk.tries >= 3:
                        raise Exception(f"Summary+Chunk step failed after retries: {e}")
                    
                    raise
            else:
                step_state = getattr(pipeline_state, step_name)

                if step_state.status == StepStatus.DONE:
                    logger.info(f"Step {step_name} already done, skipping")
                    continue

                try:
                    pipeline_state.mark_step_started(step_name)
                    self._save_pipeline_state(uow, document_id, pipeline_state)

                    self._broadcast_event(
                        project_id=project_id,
                        task_id=task_id,
                        document_id=document_id,
                        status=task_status_enum,
                        actual_progress=max(0.0, progress - 5.0),
                        current_step=step_name,
                        stage_label=stage_label,
                        step_upper_bound=upper_bound,
                        estimated_duration_ms=duration_ms,
                    )

                    if step_name in self.handlers:
                        handler_fn = self.handlers[step_name]
                        handler_kwargs = {"task_id": task_id} if "task_id" in inspect.signature(handler_fn).parameters else {}
                        handler_result = await handler_fn(
                            uow,
                            document_id,
                            project_id,
                            pipeline_state,
                            **handler_kwargs
                        )

                        if handler_result:
                            self._merge_handler_result(pipeline_state, handler_result, result)

                    pipeline_state.mark_step_completed(step_name)
                    self._save_pipeline_state(uow, document_id, pipeline_state)

                    document.status = doc_status

                    step_meta = {
                        "stage_label": stage_label,
                        "step_upper_bound": upper_bound,
                        "current_step": step_name,
                    }
                    uow.ingestion_tasks.update_task_progress(
                        task_id,
                        task_status_enum,
                        progress,
                        progress_metadata=step_meta
                    )
                    uow.commit()

                    self._broadcast_event(
                        project_id=project_id,
                        task_id=task_id,
                        document_id=document_id,
                        status=task_status_enum,
                        actual_progress=progress,
                        current_step=step_name,
                        stage_label=stage_label,
                        step_upper_bound=upper_bound,
                        estimated_duration_ms=duration_ms,
                    )
                    
                except Exception as e:
                    logger.error(f"Step {step_name} failed: {e}")
                    pipeline_state.mark_step_failed(step_name, str(e))
                    self._save_pipeline_state(uow, document_id, pipeline_state)
                    
                    if step_state.tries >= 3:
                        raise Exception(f"Step {step_name} failed after {step_state.tries} attempts: {e}")
                    
                    raise
        
        return result
    
    def _merge_handler_result(
        self,
        pipeline_state: PipelineState,
        handler_result: dict[str, Any],
        result: dict[str, Any]
    ) -> None:
        if "global_summary" in handler_result:
            pipeline_state.global_summary = handler_result["global_summary"]
        
        if "chunk_hashes" in handler_result:
            pipeline_state.chunk_hashes.extend(handler_result["chunk_hashes"])
        
        if "new_chunk_ids" in handler_result:
            pipeline_state.new_chunk_ids.extend(handler_result["new_chunk_ids"])
        
        if "existing_chunk_ids" in handler_result:
            pipeline_state.existing_chunk_ids.extend(handler_result["existing_chunk_ids"])
        
        if "embedded_chunk_ids" in handler_result:
            pipeline_state.embedded_chunk_ids.extend(handler_result["embedded_chunk_ids"])
        
        if "failed_chunk_ids" in handler_result:
            pipeline_state.failed_chunk_ids.extend(handler_result["failed_chunk_ids"])
            result["failed_chunk_ids"].extend(handler_result["failed_chunk_ids"])
        
        if "chunk_count" in handler_result:
            result["chunk_count"] = handler_result["chunk_count"]

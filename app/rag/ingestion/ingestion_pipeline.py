from uuid import UUID
from datetime import datetime
from typing import Optional, Callable, Any
import logging
import asyncio

from app.rag.ingestion.pipeline_state import PipelineState
from app.shared.enums import DocumentStatus, IngestionTaskStatus, StepStatus
from app.core.unit_of_work import UnitOfWork
from app.rag.ingestion.handlers.parse_handler import parse_handler
from app.rag.ingestion.handlers.virus_scan_handler import virus_scan_handler
from app.rag.ingestion.handlers.summary_handler import summary_handler
from app.rag.ingestion.handlers.chunk_handler import chunk_handler
from app.rag.ingestion.handlers.dedup_handler import dedup_handler
from app.rag.ingestion.handlers.enrich_handler import enrich_handler
from app.rag.ingestion.handlers.embed_handler import embed_handler
from app.rag.ingestion.handlers.link_handler import link_handler
from app.rag.ingestion.handlers.finalize_handler import finalize_handler

logger = logging.getLogger(__name__)


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
            
            uow.ingestion_tasks.update_task_progress(
                task_id,
                IngestionTaskStatus.PARSING,
                0.0,
                started_at=datetime.utcnow(),
                worker_id=worker_id
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
                
                if result["failed_chunk_ids"]:
                    document.status = DocumentStatus.COMPLETED_WITH_WARNINGS
                    document.has_partial_failures = True
                else:
                    document.status = DocumentStatus.COMPLETED
                
                document.chunk_count = result["chunk_count"]
                
                uow.ingestion_tasks.update_task_progress(
                    task_id,
                    IngestionTaskStatus.COMPLETED,
                    100.0,
                    completed_at=datetime.utcnow()
                )
                
                uow.commit()
                
                return {
                    "status": "completed",
                    "chunk_count": result["chunk_count"],
                    "failed_chunk_ids": result["failed_chunk_ids"],
                }
                
            except Exception as e:
                logger.exception(f"Pipeline failed for document {document_id}")
                
                uow.ingestion_tasks.update_task_progress(
                    task_id,
                    IngestionTaskStatus.FAILED,
                    task.progress,
                    error_message=str(e),
                    last_error_step=pipeline_state.get_next_step()
                )
                
                document.status = DocumentStatus.FAILED
                
                uow.commit()
                raise
    
    def _load_pipeline_state(self, document) -> PipelineState:
        if document.pipeline_state:
            return PipelineState.model_validate(document.pipeline_state)
        return PipelineState()
    
    def _save_pipeline_state(
        self,
        uow,
        document_id: UUID,
        pipeline_state: PipelineState
    ) -> None:
        uow.documents.update_pipeline_state(document_id, pipeline_state.model_dump())
    
    async def _execute_pipeline(
        self,
        uow,
        task_id: UUID,
        document_id: UUID,
        project_id: UUID,
        pipeline_state: PipelineState,
        worker_id: Optional[str]
    ) -> dict[str, Any]:

        steps_progress = {
            "virus_scan": (10.0, DocumentStatus.PARSING),  # TODO: Add DocumentStatus.QUARANTINED for infected files
            "parse": (15.0, DocumentStatus.PARSED),
            "summary_chunk": (50.0, DocumentStatus.CHUNKING),  # Combined step
            "dedup": (65.0, DocumentStatus.DEDUPED),
            "enrich": (80.0, DocumentStatus.ENRICHED),
            "embed": (90.0, DocumentStatus.EMBEDDING),
            "link": (95.0, DocumentStatus.LINKED),
            "finalize": (100.0, DocumentStatus.COMPLETED),
        }
        
        result = {
            "chunk_count": 0,
            "failed_chunk_ids": [],
        }
        
        for step_name, (progress, doc_status) in steps_progress.items():
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
                    
                    summary_task = asyncio.create_task(
                        self.handlers["summary"](uow, document_id, project_id, pipeline_state)
                    )
                    chunk_task = asyncio.create_task(
                        self.handlers["chunk"](uow, document_id, project_id, pipeline_state)
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
                    
                    uow.ingestion_tasks.update_task_progress(
                        task_id,
                        IngestionTaskStatus.CHUNKING,
                        progress
                    )
                    uow.commit()
                    
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

                    if step_name in self.handlers:
                        handler_result = await self.handlers[step_name](
                            uow,
                            document_id,
                            project_id,
                            pipeline_state
                        )

                        if handler_result:
                            self._merge_handler_result(pipeline_state, handler_result, result)

                    pipeline_state.mark_step_completed(step_name)
                    self._save_pipeline_state(uow, document_id, pipeline_state)

                    document.status = doc_status

                    uow.ingestion_tasks.update_task_progress(
                        task_id,
                        IngestionTaskStatus(step_name.upper()),
                        progress
                    )
                    uow.commit()
                    
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

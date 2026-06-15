from uuid import UUID
from typing import Dict, Any
import logging
from app.config.settings import settings
from app.observability.metrics import track_step_duration

logger = logging.getLogger(__name__)


@track_step_duration("finalize")
async def finalize_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state
) -> Dict[str, Any]:

    document = uow.documents.get(document_id)
    
    if not document:
        raise ValueError(f"Document {document_id} not found")
    
    failed_chunk_ids = pipeline_state.failed_chunk_ids
    total_chunks = len(pipeline_state.new_chunk_ids) + len(pipeline_state.existing_chunk_ids)
    
    if failed_chunk_ids:
        document.status = "completed_with_warnings"
        document.has_partial_failures = True
        logger.warning(
            f"Document {document_id} completed with {len(failed_chunk_ids)} failed chunks "
            f"out of {total_chunks} total"
        )
    else:
        document.status = "completed"
        document.has_partial_failures = False
        logger.info(f"Document {document_id} completed successfully with {total_chunks} chunks")
    
    document.chunk_count = total_chunks
    
    if pipeline_state.global_summary:
        if not document.processing_metadata:
            document.processing_metadata = {}
        document.processing_metadata["global_summary"] = pipeline_state.global_summary
    
    if not document.processing_metadata:
        document.processing_metadata = {}
    document.processing_metadata.update({
        "total_chunks": total_chunks,
        "new_chunks": len(pipeline_state.new_chunk_ids),
        "existing_chunks": len(pipeline_state.existing_chunk_ids),
        "failed_chunks": len(failed_chunk_ids),
        "pipeline_steps_completed": [
            step for step in ["parse", "summary", "chunk", "dedup", "enrich", "embed", "link"]
            if getattr(pipeline_state, step).status == "done"
        ]
    })
    
    if settings.CLEANUP_PIPELINE_STATE_ON_COMPLETION:
        logger.info(f"Cleaning up pipeline state for document {document_id}")
        document.pipeline_state = {}
    else:
        logger.info(f"Preserving pipeline state for document {document_id} (debugging)")
    
    uow.commit()
    
    return {
        "status": document.status,
        "chunk_count": total_chunks,
        "failed_chunk_ids": failed_chunk_ids,
    }

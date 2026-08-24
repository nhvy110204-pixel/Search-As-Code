from uuid import UUID
from typing import Dict, Any
from datetime import datetime
import logging

from app.config.settings import settings
from app.observability.metrics import track_step_duration
from app.services.core.redis_service import redis_cache_service
from app.shared.enums import DocumentStatus
from app.core.exceptions import ReconciliationError
from app.rag.ingestion.constants import PARTIAL_FAILURE_MAX_RATIO

logger = logging.getLogger(__name__)


@track_step_duration("finalize")
async def finalize_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state
) -> Dict[str, Any]:
    """
    Tier 5 Ingestion Pipeline Finalize Handler with Hard Reconciliation Gate.
    Enforces data integrity invariants (Links == Chunks == Embedded Vectors)
    before permitting document state transition to READY or PARTIALLY_AVAILABLE.
    """
    document = uow.documents.get(document_id)
    
    if not document:
        raise ValueError(f"Document {document_id} not found")
    
    failed_chunk_ids = pipeline_state.failed_chunk_ids
    total_processed_chunks = len(pipeline_state.new_chunk_ids) + len(pipeline_state.existing_chunk_ids)
    expected_chunks = pipeline_state.expected_chunk_count if pipeline_state.expected_chunk_count > 0 else total_processed_chunks
    actual_links = pipeline_state.actual_link_count if pipeline_state.actual_link_count > 0 else total_processed_chunks
    actual_embedded = pipeline_state.actual_embedded_count if pipeline_state.actual_embedded_count > 0 else (len(pipeline_state.embedded_chunk_ids) + len(pipeline_state.existing_chunk_ids))
    
    failed_chunks_count = len(failed_chunk_ids)
    failed_ratio = failed_chunks_count / max(1, expected_chunks)
    
    # -------------------------------------------------------------
    # 1. Build Reconciliation Invariant Report
    # -------------------------------------------------------------
    reconciliation_report = {
        "expected_chunk_count": expected_chunks,
        "actual_link_count": actual_links,
        "actual_embedded_count": actual_embedded,
        "failed_chunk_count": failed_chunks_count,
        "failed_ratio": round(failed_ratio, 4),
        "is_invariant_matched": (actual_links == expected_chunks and failed_chunks_count == 0),
        "evaluated_at": datetime.utcnow().isoformat(),
    }
    pipeline_state.reconciliation_report = reconciliation_report
    
    # -------------------------------------------------------------
    # 2. Hard Reconciliation Invariant Validation
    # -------------------------------------------------------------
    # Invariant A: Significant link creation mismatch
    if expected_chunks > 0 and actual_links < int(expected_chunks * 0.90):
        err_msg = (
            f"Reconciliation Invariant Violated: Document {document_id} expected {expected_chunks} chunks "
            f"but only {actual_links} links were created."
        )
        logger.error(err_msg)
        raise ReconciliationError(err_msg, report=reconciliation_report, is_retryable=True)
    
    # Invariant B: Failed chunk ratio exceeds acceptable threshold (5%)
    if failed_ratio >= PARTIAL_FAILURE_MAX_RATIO and failed_chunks_count > 0:
        err_msg = (
            f"Reconciliation Threshold Exceeded: Document {document_id} has {failed_chunks_count}/{expected_chunks} "
            f"failed chunks ({failed_ratio:.1%}), exceeding tolerance of {PARTIAL_FAILURE_MAX_RATIO:.1%}."
        )
        logger.error(err_msg)
        raise ReconciliationError(err_msg, report=reconciliation_report, is_retryable=True)
    
    # -------------------------------------------------------------
    # 3. Assign Business DocumentStatus
    # -------------------------------------------------------------
    if failed_chunks_count > 0:
        # Tolerable minor loss (< 5%) -> Mark as PARTIALLY_AVAILABLE (completed with warnings)
        document.status = DocumentStatus.PARTIALLY_AVAILABLE
        document.has_partial_failures = True
        logger.warning(
            f"Document {document_id} passed Reconciliation Gate with PARTIALLY_AVAILABLE status "
            f"({failed_chunks_count}/{expected_chunks} failed chunks, ratio={failed_ratio:.1%})"
        )
    else:
        document.status = DocumentStatus.READY
        document.has_partial_failures = False
        logger.info(
            f"Document {document_id} passed Reconciliation Gate with 100% invariant match "
            f"({expected_chunks} chunks, {actual_embedded} vectors, {actual_links} links)"
        )
    
    document.chunk_count = total_processed_chunks
    
    if pipeline_state.global_summary:
        if not document.processing_metadata:
            document.processing_metadata = {}
        document.processing_metadata["global_summary"] = pipeline_state.global_summary
    
    if not document.processing_metadata:
        document.processing_metadata = {}
        
    document.processing_metadata.update({
        "total_chunks": total_processed_chunks,
        "new_chunks": len(pipeline_state.new_chunk_ids),
        "existing_chunks": len(pipeline_state.existing_chunk_ids),
        "failed_chunks": failed_chunks_count,
        "reconciliation_report": reconciliation_report,
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
    
    # Invalidate project documents metadata cache
    try:
        if redis_cache_service.redis:
            cache_key = f"project:{project_id}:documents_metadata"
            redis_cache_service.redis.delete(cache_key)
            logger.info(f"Invalidated project documents metadata cache in finalize_handler: project_id={project_id}")
    except Exception as cache_err:
        logger.warning(f"Failed to invalidate project documents metadata cache in finalize_handler: {cache_err}")
    
    return {
        "status": document.status.value if hasattr(document.status, "value") else str(document.status),
        "chunk_count": total_processed_chunks,
        "failed_chunk_ids": failed_chunk_ids,
        "reconciliation_report": reconciliation_report,
    }

from uuid import UUID
from typing import Dict, Any
import logging
from app.observability.metrics import track_step_duration, set_chunk_dedup_ratio

logger = logging.getLogger(__name__)


@track_step_duration("dedup")
async def dedup_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state
) -> Dict[str, Any]:

    document = uow.documents.get(document_id)
    
    if not document:
        raise ValueError(f"Document {document_id} not found")
    
    chunk_data_list = pipeline_state.chunk.metadata.get("chunk_data_list", [])
    
    if not chunk_data_list:
        logger.warning(f"No chunk data found in pipeline state for document {document_id}")
        return {
            "new_chunk_ids": [],
            "existing_chunk_ids": [],
        }

    results = uow.document_chunks.batch_insert_chunks_if_not_exists(chunk_data_list)
    
    new_chunk_ids = []
    existing_chunk_ids = []
    
    for chunk, is_new in results:
        if is_new:
            new_chunk_ids.append(str(chunk.id))
        else:
            existing_chunk_ids.append(str(chunk.id))
    
    pipeline_state.new_chunk_ids = new_chunk_ids
    
    pipeline_state.existing_chunk_ids = existing_chunk_ids
    
    total_chunks = len(new_chunk_ids) + len(existing_chunk_ids)
    if total_chunks > 0:
        dedup_ratio = len(existing_chunk_ids) / total_chunks
        set_chunk_dedup_ratio(str(document_id), dedup_ratio)
    
    logger.info(
        f"Dedup completed for document {document_id}: "
        f"{len(new_chunk_ids)} new, {len(existing_chunk_ids)} existing"
    )
    
    return {
        "new_chunk_ids": new_chunk_ids,
        "existing_chunk_ids": existing_chunk_ids,
    }

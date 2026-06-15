from uuid import UUID
from typing import Dict, Any
import logging
from app.observability.metrics import track_step_duration

logger = logging.getLogger(__name__)


@track_step_duration("link")
async def link_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state
) -> Dict[str, Any]:

    document = uow.documents.get(document_id)
    
    if not document:
        raise ValueError(f"Document {document_id} not found")
    
    all_chunk_ids = pipeline_state.new_chunk_ids + pipeline_state.existing_chunk_ids
    
    if not all_chunk_ids:
        logger.warning(f"No chunks to link for document {document_id}")
        return {}
    
    linked_count = 0
    try:
        chunk_uuids = [UUID(cid) for cid in all_chunk_ids]
        uow.document_chunk_links.batch_create_links(document_id, chunk_uuids)
        linked_count = len(all_chunk_ids)
    except Exception as e:
        logger.error(f"Failed to batch create links for document {document_id}: {e}. Falling back to individual creation.")
        for chunk_id_str in all_chunk_ids:
            chunk_id = UUID(chunk_id_str)
            try:
                uow.document_chunk_links.create_link(document_id, chunk_id)
                linked_count += 1
            except Exception as inner_e:
                logger.error(f"Failed to create individual link for chunk {chunk_id}: {inner_e}")
    
    logger.info(f"Created {linked_count} chunk-document links for document {document_id}")
    
    return {
        "linked_count": linked_count,
    }

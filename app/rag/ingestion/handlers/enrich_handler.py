from uuid import UUID
from typing import Dict, Any
import logging
from app.observability.metrics import track_step_duration

logger = logging.getLogger(__name__)


@track_step_duration("enrich")
async def enrich_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state
) -> Dict[str, Any]:

    document = uow.documents.get(document_id)
    
    if not document:
        raise ValueError(f"Document {document_id} not found")
    
    new_chunk_ids = pipeline_state.new_chunk_ids
    
    if not new_chunk_ids:
        logger.info(f"No new chunks to enrich for document {document_id}")
        return {}
    
    title = document.file_name
    summary = pipeline_state.global_summary or "No summary available"
    
    enriched_count = 0
    for chunk_id_str in new_chunk_ids:
        chunk_id = UUID(chunk_id_str)
        chunk = uow.document_chunks.get(chunk_id)
        
        if not chunk:
            logger.warning(f"Chunk {chunk_id} not found for enrichment")
            continue
        
        enriched_content = f"# Document: {title}\n\n## Summary\n{summary}\n\n## Content\n{chunk.content}"
        
        uow.document_chunks.update_enriched_content(chunk_id, enriched_content)
        enriched_count += 1
    
    logger.info(f"Enriched {enriched_count} chunks for document {document_id}")
    
    return {
        "enriched_count": enriched_count,
    }

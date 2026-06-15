from uuid import UUID, uuid4
from typing import Dict, Any, List
import logging
from app.rag.embeddings.service import EmbeddingService
from app.core.qdrant import qdrant_manager
from app.config.settings import settings
from app.core.utils import count_tokens, count_tokens_batch, get_embedding_cost
from app.observability.metrics import (
    track_step_duration,
    track_embedding_batch_size,
    track_cost,
    track_qdrant_upsert
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 10  


@track_step_duration("embed")
async def embed_handler(
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
        logger.info(f"No new chunks to embed for document {document_id}")
        return {
            "embedded_chunk_ids": [],
            "failed_chunk_ids": [],
        }
    
    embedding_service = EmbeddingService()
    
    embedded_chunk_ids = []
    failed_chunk_ids = []
    
    for i in range(0, len(new_chunk_ids), BATCH_SIZE):
        batch_chunk_ids = new_chunk_ids[i:i + BATCH_SIZE]
        
        track_embedding_batch_size(len(batch_chunk_ids))
        
        batch_data = []
        batch_chunk_id_map = {}
        
        for chunk_id_str in batch_chunk_ids:
            chunk_id = UUID(chunk_id_str)
            chunk = uow.document_chunks.get(chunk_id)
            
            if not chunk:
                logger.warning(f"Chunk {chunk_id} not found")
                failed_chunk_ids.append(chunk_id_str)
                uow.document_chunks.update_embed_status(chunk_id, "failed")
                continue
            
            content = chunk.enriched_content if chunk.enriched_content else chunk.content
            
            if not content:
                logger.warning(f"Chunk {chunk_id} has no content")
                failed_chunk_ids.append(chunk_id_str)
                uow.document_chunks.update_embed_status(chunk_id, "failed")
                continue
            
            batch_data.append({
                "chunk_id": chunk_id,
                "chunk_id_str": chunk_id_str,
                "content": content,
                "chunk_index": chunk.chunk_index,
            })
            batch_chunk_id_map[chunk_id_str] = chunk
        
        if not batch_data:
            continue
        try:
            texts = [item["content"] for item in batch_data]
            vectors = await embedding_service.embed_texts_async(texts)
            
            tokens = count_tokens_batch(texts, settings.EMBEDDING_MODEL_NAME)
            cost = get_embedding_cost(tokens, settings.EMBEDDING_MODEL_NAME)
            track_cost("embedding", cost)
            
            for idx, (item, vector) in enumerate(zip(batch_data, vectors)):
                chunk_id = item["chunk_id"]
                chunk_id_str = item["chunk_id_str"]
                
                try:
                    embedding_id = uuid4()
                    
                    qdrant_manager.upsert_vector(
                        collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                        embedding_id=embedding_id,
                        vector=vector,
                        payload={
                            "document_id": str(document_id),
                            "chunk_index": item["chunk_index"],
                            "content": item["content"],
                            "project_id": str(project_id),
                        },
                    )
                    
                    track_qdrant_upsert("success")
                    
                    chunk = batch_chunk_id_map[chunk_id_str]
                    chunk.embedding_id = embedding_id
                    uow.document_chunks.update_embed_status(chunk_id, "done")
                    embedded_chunk_ids.append(chunk_id_str)
                    
                except Exception as e:
                    logger.error(f"Failed to embed chunk {chunk_id}: {e}")
                    uow.document_chunks.update_embed_status(chunk_id, "failed")
                    failed_chunk_ids.append(chunk_id_str)
                    track_qdrant_upsert("failed")
            
            uow.commit()
            
        except Exception as e:
            logger.warning(
                f"Batch embedding failed for document {document_id}: {e}. "
                f"Falling back to embedding chunks individually."
            )
            for item in batch_data:
                chunk_id = item["chunk_id"]
                chunk_id_str = item["chunk_id_str"]
                
                try:
                    vector = await embedding_service.embed_text_async(item["content"])
                    
                    tokens = count_tokens(item["content"], settings.EMBEDDING_MODEL_NAME)
                    cost = get_embedding_cost(tokens, settings.EMBEDDING_MODEL_NAME)
                    track_cost("embedding", cost)
                    
                    embedding_id = uuid4()
                    qdrant_manager.upsert_vector(
                        collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                        embedding_id=embedding_id,
                        vector=vector,
                        payload={
                            "document_id": str(document_id),
                            "chunk_index": item["chunk_index"],
                            "content": item["content"],
                            "project_id": str(project_id),
                        },
                    )
                    
                    track_qdrant_upsert("success")
                    
                    chunk = batch_chunk_id_map[chunk_id_str]
                    chunk.embedding_id = embedding_id
                    uow.document_chunks.update_embed_status(chunk_id, "done")
                    embedded_chunk_ids.append(chunk_id_str)
                    
                except Exception as inner_e:
                    logger.error(f"Failed to embed individual chunk {chunk_id}: {inner_e}")
                    uow.document_chunks.update_embed_status(chunk_id, "failed")
                    failed_chunk_ids.append(chunk_id_str)
                    track_qdrant_upsert("failed")
            
            uow.commit()

    pipeline_state.embedded_chunk_ids = embedded_chunk_ids
    pipeline_state.failed_chunk_ids = failed_chunk_ids
    
    logger.info(
        f"Embedding completed for document {document_id}: "
        f"{len(embedded_chunk_ids)} embedded, {len(failed_chunk_ids)} failed"
    )
    
    return {
        "embedded_chunk_ids": embedded_chunk_ids,
        "failed_chunk_ids": failed_chunk_ids,
    }

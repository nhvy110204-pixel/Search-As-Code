from uuid import UUID, uuid4
from typing import Dict, Any, List, Optional
import logging

try:
    import blake3
except ImportError:
    import hashlib
    class _Blake3Shim:
        def __init__(self, data: bytes = b""):
            self._h = hashlib.sha256(data)
        def update(self, data: bytes):
            self._h.update(data)
        def hexdigest(self):
            return self._h.hexdigest()
    class _Blake3ModuleShim:
        @staticmethod
        def blake3(data: bytes = b""):
            return _Blake3Shim(data)
    blake3 = _Blake3ModuleShim()

from app.rag.embeddings.service import EmbeddingService
from app.core.qdrant import qdrant_manager
from app.config.settings import settings
from app.core.utils import count_tokens, count_tokens_batch, get_embedding_cost
from app.core.retry import retry_with_backoff
from app.rag.ingestion.constants import DEFAULT_EMBEDDING_VERSION
from app.observability.metrics import (
    track_step_duration,
    track_embedding_batch_size,
    track_cost,
    track_qdrant_upsert
)
from app.shared.enums import IngestionTaskStatus

logger = logging.getLogger(__name__)

BATCH_SIZE = 10  


@retry_with_backoff(max_retries=3, base_delay=1.0, timeout_seconds=20.0)
async def _embed_batch_with_retry(embedding_service: EmbeddingService, texts: List[str]) -> List[List[float]]:
    return await embedding_service.embed_texts_async(texts)


@retry_with_backoff(max_retries=3, base_delay=1.0, timeout_seconds=20.0)
async def _embed_single_with_retry(embedding_service: EmbeddingService, text: str) -> List[float]:
    return await embedding_service.embed_text_async(text)


@retry_with_backoff(max_retries=3, base_delay=0.5, timeout_seconds=15.0)
def _upsert_qdrant_with_retry(collection_name: str, embedding_id: UUID, vector: List[float], payload: dict):
    qdrant_manager.upsert_vector(
        collection_name=collection_name,
        embedding_id=embedding_id,
        vector=vector,
        payload=payload
    )  


@track_step_duration("embed")
async def embed_handler(
    uow,
    document_id: UUID,
    project_id: UUID,
    pipeline_state,
    task_id: Optional[UUID] = None
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
            vectors = await _embed_batch_with_retry(embedding_service, texts)
            
            tokens = count_tokens_batch(texts, settings.EMBEDDING_MODEL_NAME)
            cost = get_embedding_cost(tokens, settings.EMBEDDING_MODEL_NAME)
            track_cost("embedding", cost)
            
            for idx, (item, vector) in enumerate(zip(batch_data, vectors)):
                chunk_id = item["chunk_id"]
                chunk_id_str = item["chunk_id_str"]
                
                try:
                    embedding_id = uuid4()
                    
                    # 4-tier Embedding Fingerprint: tracks model versioning and vector deterministic cache
                    hasher = blake3.blake3()
                    hasher.update(f"{chunk_id}:{settings.EMBEDDING_MODEL_NAME}:{DEFAULT_EMBEDDING_VERSION}".encode('utf-8'))
                    embedding_fingerprint = hasher.hexdigest()
                    
                    _upsert_qdrant_with_retry(
                        collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                        embedding_id=embedding_id,
                        vector=vector,
                        payload={
                            "document_id": str(document_id),
                            "chunk_index": item["chunk_index"],
                            "content": item["content"],
                            "project_id": str(project_id),
                            "embedding_fingerprint": embedding_fingerprint,
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
                    vector = await _embed_single_with_retry(embedding_service, item["content"])
                    
                    tokens = count_tokens(item["content"], settings.EMBEDDING_MODEL_NAME)
                    cost = get_embedding_cost(tokens, settings.EMBEDDING_MODEL_NAME)
                    track_cost("embedding", cost)
                    
                    embedding_id = uuid4()
                    hasher = blake3.blake3()
                    hasher.update(f"{chunk_id}:{settings.EMBEDDING_MODEL_NAME}:{DEFAULT_EMBEDDING_VERSION}".encode('utf-8'))
                    embedding_fingerprint = hasher.hexdigest()

                    _upsert_qdrant_with_retry(
                        collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                        embedding_id=embedding_id,
                        vector=vector,
                        payload={
                            "document_id": str(document_id),
                            "chunk_index": item["chunk_index"],
                            "content": item["content"],
                            "project_id": str(project_id),
                            "embedding_fingerprint": embedding_fingerprint,
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

        # Real-time incremental progress update in DB: Embedding phase is [75.0% -> 95.0%]
        if uow and task_id and len(new_chunk_ids) > 0:
            try:  
                from datetime import datetime
                from app.services.core.redis_service import redis_cache_service

                processed_count = min(len(new_chunk_ids), i + len(batch_chunk_ids))
                total_chunks = len(new_chunk_ids)
                embed_pct = 75.0 + (processed_count / total_chunks) * 20.0
                stage_label = f"Đang vector hóa tri thức ({processed_count}/{total_chunks} chunks)..."
                progress_metadata = {
                    "stage_label": stage_label,
                    "processed_units": processed_count,
                    "total_units": total_chunks,
                    "unit_name": "chunks",
                    "step_upper_bound": 95.0,
                    "current_step": "embed",
                }
                uow.ingestion_tasks.update_task_progress(
                    task_id,
                    IngestionTaskStatus.EMBEDDING,
                    round(embed_pct, 1),
                    progress_metadata=progress_metadata
                )
                uow.commit()

                if project_id and document_id:
                    redis_cache_service.publish_ingestion_event(
                        project_id=project_id,
                        event_data={
                            "event_id": f"evt-{task_id}-{int(datetime.utcnow().timestamp() * 1000)}",
                            "seq_num": int(datetime.utcnow().timestamp() * 1000),
                            "task_id": str(task_id),
                            "document_id": str(document_id),
                            "project_id": str(project_id),
                            "status": IngestionTaskStatus.EMBEDDING.value,
                            "actual_progress": round(embed_pct, 1),
                            "current_step": "embed",
                            "stage_label": stage_label,
                            "processed_units": processed_count,
                            "total_units": total_chunks,
                            "unit_name": "chunks",
                            "step_upper_bound": 95.0,
                            "estimated_duration_ms": 800,
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )
            except Exception as prog_err:
                logger.debug(f"Failed to update incremental embed progress: {prog_err}")

    pipeline_state.embedded_chunk_ids = embedded_chunk_ids
    pipeline_state.failed_chunk_ids = failed_chunk_ids
    pipeline_state.actual_embedded_count = len(embedded_chunk_ids) + len(pipeline_state.existing_chunk_ids)
    
    logger.info(
        f"Embedding completed for document {document_id}: "
        f"{len(embedded_chunk_ids)} newly embedded, {len(pipeline_state.existing_chunk_ids)} existing, "
        f"{len(failed_chunk_ids)} failed (actual_embedded_count={pipeline_state.actual_embedded_count})"
    )
    
    return {
        "embedded_chunk_ids": embedded_chunk_ids,
        "failed_chunk_ids": failed_chunk_ids,
        "actual_embedded_count": pipeline_state.actual_embedded_count,
    }

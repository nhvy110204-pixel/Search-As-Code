"""Service for DocumentChunk embedding operations."""

import hashlib
from typing import List, Optional
from uuid import UUID, uuid4
import tiktoken

from sqlalchemy.orm import Session
from qdrant_client.http.models import Filter, FieldCondition, MatchValue

from app.models.document import DocumentChunk
from app.schemas.dto.chunk_embedding import (
    ChunkEmbeddingCreateDTO,
    ChunkEmbeddingResponseDTO,
)
from app.repositories.document_chunk import DocumentChunkRepository
from app.services.core.base import BaseService
from app.rag.embeddings.service import EmbeddingService
from app.core.qdrant import qdrant_manager
from app.config.settings import settings
from app.core.logger import service_boundary 


class DocumentChunkEmbeddingService(BaseService[DocumentChunk, ChunkEmbeddingCreateDTO, ChunkEmbeddingCreateDTO]):
    
    def __init__(self, db: Session):
        super().__init__(DocumentChunkRepository(db))
        self.embedding_service = EmbeddingService()
        self.qdrant = qdrant_manager
        
        try:
            self._tokenizer = tiktoken.encoding_for_model(self.embedding_service.model_name)
        except Exception:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
    
    def _count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text)) if text else 0

    @service_boundary("Create Chunk with Embedding")
    async def create_chunk_with_embedding_async(
        self,
        document_id: UUID,
        chunk_index: int,
        content: str,
        page_number: Optional[int] = None,
        meta_data: Optional[dict] = None,
    ) -> Optional[DocumentChunk]:
        
        if not content or not content.strip():
            raise ValueError("Chunk content cannot be empty")
 
        vector = await self.embedding_service.embed_text_async(content)
        embedding_id = uuid4()
 
        self.qdrant.upsert_vector(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            embedding_id=embedding_id,
            vector=vector,
            payload={
                "document_id": str(document_id),
                "chunk_index": chunk_index,
                "content": content,
                "page_number": page_number,
                **(meta_data or {}),
            },
        )
        
        return self.repo.create_with_embedding_id(
            document_id=document_id,
            chunk_index=chunk_index,
            content=content,
            embedding_id=embedding_id,
            chunk_hash=hashlib.sha256(content.encode()).hexdigest(),
            token_count=self._count_tokens(content),
            page_number=page_number,
            meta_data=meta_data or {},
        )

    @service_boundary("Search Chunks by Similarity")
    async def search_chunks_by_similarity_async(
        self,
        query: str,
        document_id: Optional[UUID] = None,
        limit: int = 10,
        score_threshold: float = 0.5,
    ) -> List[ChunkEmbeddingResponseDTO]:
        
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
            
        query_vector = await self.embedding_service.embed_text_async(query)
        results = self.qdrant.search_vectors(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
        )
        
        if not results:
            return []
            
        embedding_ids = [res["embedding_id"] for res in results]
        scores_map = {res["embedding_id"]: res["score"] for res in results}
        
        filters = {"embedding_id__in": embedding_ids}
        if document_id:
            filters["document_id"] = document_id
            
        db_chunks = self.repo.get_multi(filters=filters, limit=len(embedding_ids))
        chunks_dict = {chunk.embedding_id: chunk for chunk in db_chunks}
        
        response_dtos = []
        for emb_id in embedding_ids:
            db_chunk = chunks_dict.get(emb_id)
            if db_chunk:
                response_dtos.append(ChunkEmbeddingResponseDTO(
                    chunk_id=db_chunk.id,
                    embedding_id=emb_id,
                    score=scores_map[emb_id],
                    content=db_chunk.content,
                    document_id=db_chunk.document_id,
                    chunk_index=db_chunk.chunk_index,
                    page_number=db_chunk.page_number,
                    meta_data=db_chunk.meta_data,
                ))
        return response_dtos

    @service_boundary("Delete Single Chunk Embedding")
    def delete_chunk_embedding(self, chunk_id: UUID, hard: bool = True) -> bool:
        db_chunk = self.get(chunk_id)
        if not db_chunk:
            raise ValueError(f"Chunk {chunk_id} not found")
            
        self.qdrant.delete_vector(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            embedding_id=db_chunk.embedding_id,
        )
        return self.delete(chunk_id, hard=hard)

    @service_boundary("Bulk Delete Document Embeddings")
    def delete_document_embeddings(self, document_id: UUID, hard: bool = True) -> int:
        qdrant_filter = Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]
        )
        self.qdrant.delete_vectors_by_filter(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            filter_condition=qdrant_filter,
        )
        return self.repo.delete_by_document(document_id, hard=hard)

    @service_boundary("Re-embed Single Chunk")
    async def reembed_chunk_async(self, chunk_id: UUID) -> Optional[DocumentChunk]:
        db_chunk = self.get(chunk_id)
        if not db_chunk:
            raise ValueError(f"Chunk {chunk_id} not found")
            
        self.qdrant.delete_vector(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            embedding_id=db_chunk.embedding_id,
        )
        
        new_vector = await self.embedding_service.embed_text_async(db_chunk.content)
        new_embedding_id = uuid4()
        
        self.qdrant.upsert_vector(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            embedding_id=new_embedding_id,
            vector=new_vector,
            payload={
                "document_id": str(db_chunk.document_id),
                "chunk_index": db_chunk.chunk_index,
                "content": db_chunk.content,
                "page_number": db_chunk.page_number,
                **db_chunk.meta_data,
            },
        )
        return self.repo.update_embedding_id(chunk_id, new_embedding_id)
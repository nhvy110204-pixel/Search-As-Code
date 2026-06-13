"""Service for DocumentChunk embedding operations."""

import hashlib
from typing import List, Optional
from uuid import UUID, uuid4
import tiktoken

from qdrant_client.http.models import Filter, FieldCondition, MatchValue

from app.models.document import DocumentChunk
from app.schemas.dto.document_chunk import (
    DocumentChunkCreate,
    DocumentChunkUpdate,
)
from app.services.core.document_chunk import DocumentChunkService
from app.rag.embeddings.service import EmbeddingService
from app.core.qdrant import qdrant_manager
from app.config.settings import settings
from app.core.logger import service_boundary 


class DocumentChunkEmbeddingService:
    """
    Specialized service for DocumentChunk operations with Qdrant embedding sync.
    Wraps DocumentChunkService with embedding-aware business logic.
    """
    
    def __init__(self, chunk_service: DocumentChunkService):
        self.chunk_service = chunk_service
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
        
        # Create chunk using service.create() with proper DTO
        chunk_create = DocumentChunkCreate(
            document_id=document_id,
            chunk_index=chunk_index,
            content=content,
            embedding_id=embedding_id,
            chunk_hash=hashlib.sha256(content.encode()).hexdigest(),
            token_count=self._count_tokens(content),
            page_number=page_number,
            meta_data=meta_data or {},
        )
        return self.chunk_service.create(chunk_create)

    @service_boundary("Search Chunks by Similarity")
    async def search_chunks_by_similarity_async(
        self,
        query: str,
        document_id: Optional[UUID] = None,
        limit: int = 10,
        score_threshold: float = 0.5,
    ) -> List[DocumentChunk]:
        """Search chunks by vector similarity and return full DocumentChunk objects."""
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
        
        filters = {"embedding_id__in": embedding_ids}
        if document_id:
            filters["document_id"] = document_id
            
        db_chunks = self.chunk_service.repo.get_multi(filters=filters, limit=len(embedding_ids))
        # Return in Qdrant search order
        chunks_dict = {chunk.embedding_id: chunk for chunk in db_chunks}
        
        return [chunks_dict[emb_id] for emb_id in embedding_ids if emb_id in chunks_dict]

    @service_boundary("Delete Single Chunk Embedding")
    def delete_chunk_embedding(self, chunk_id: UUID, hard: bool = True) -> bool:
        """Delete chunk and its Qdrant embedding."""
        db_chunk = self.chunk_service.get(chunk_id)
        if not db_chunk:
            raise ValueError(f"Chunk {chunk_id} not found")
            
        self.qdrant.delete_vector(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            embedding_id=db_chunk.embedding_id,
        )
        return self.chunk_service.delete(chunk_id, hard=hard)

    @service_boundary("Bulk Delete Document Embeddings")
    def delete_document_embeddings(self, document_id: UUID, hard: bool = True) -> int:
        """Delete all chunks of document and their Qdrant embeddings."""
        qdrant_filter = Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=str(document_id)))]
        )
        self.qdrant.delete_vectors_by_filter(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            filter_condition=qdrant_filter,
        )
        return self.chunk_service.delete_by_document(document_id, hard=hard)

    @service_boundary("Re-embed Single Chunk")
    async def reembed_chunk_async(self, chunk_id: UUID) -> Optional[DocumentChunk]:
        """Re-embed a chunk with new embedding."""
        db_chunk = self.chunk_service.get(chunk_id)
        if not db_chunk:
            raise ValueError(f"Chunk {chunk_id} not found")
            
        # Delete old embedding from Qdrant
        self.qdrant.delete_vector(
            collection_name=settings.QDRANT_COLLECTION_CHUNKS,
            embedding_id=db_chunk.embedding_id,
        )
        
        # Create new embedding
        new_vector = await self.embedding_service.embed_text_async(db_chunk.content)
        new_embedding_id = uuid4()
        
        # Upsert to Qdrant
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

        update_dto = DocumentChunkUpdate(embedding_id=new_embedding_id)
        return self.chunk_service.update(chunk_id, update_dto)
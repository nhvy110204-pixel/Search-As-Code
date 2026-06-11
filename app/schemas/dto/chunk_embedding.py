"""DTOs for DocumentChunk embedding operations."""

from typing import Any, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ChunkEmbeddingCreateDTO(BaseModel):
    """DTO for creating a document chunk with embedding."""
    
    document_id: UUID = Field(..., description="Parent document ID")
    chunk_index: int = Field(..., description="Index of chunk in document")
    content: str = Field(..., description="Raw text content of chunk")
    chunk_hash: str = Field(..., description="SHA-256 hash of chunk content")
    token_count: int = Field(default=0, description="Token count via embedding model")
    page_number: Optional[int] = Field(None, description="Page number if applicable")
    meta_data: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class ChunkEmbeddingSearchDTO(BaseModel):
    """DTO for searching similar chunks."""
    
    query: str = Field(..., description="Query text to search")
    document_id: Optional[UUID] = Field(None, description="Filter by document (optional)")
    project_id: Optional[UUID] = Field(None, description="Filter by project (optional)")
    limit: int = Field(default=10, ge=1, le=100, description="Max results")
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Min similarity score")


class ChunkEmbeddingResponseDTO(BaseModel):
    """DTO for chunk search result."""
    
    chunk_id: UUID = Field(..., description="Document chunk UUID")
    embedding_id: UUID = Field(..., description="Vector ID in Qdrant")
    score: float = Field(..., description="Similarity score (0-1)")
    content: str = Field(..., description="Chunk text content")
    document_id: UUID = Field(..., description="Parent document ID")
    chunk_index: int = Field(..., description="Index in document")
    page_number: Optional[int] = Field(None, description="Page number")
    meta_data: dict[str, Any] = Field(default_factory=dict, description="Metadata")


class ChunkEmbeddingDetailDTO(BaseModel):
    """DTO for chunk with full embedding details."""
    
    chunk_id: UUID
    document_id: UUID
    content: str
    embedding_id: UUID
    chunk_hash: str
    token_count: int
    page_number: Optional[int] = None
    meta_data: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True

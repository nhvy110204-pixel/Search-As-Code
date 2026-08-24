from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from uuid import UUID


class IParseProvider(ABC):
    """Abstract interface for document parsing and structure conversion."""

    @abstractmethod
    async def parse_to_markdown(
        self,
        file_path: str,
        file_name: str,
        profile: str = "DIGITAL_BOOK"
    ) -> str:
        """Parses a document file and exports formatted Markdown string."""
        pass


class ISummarizerProvider(ABC):
    """Abstract interface for document and chunk summarization."""

    @abstractmethod
    async def generate_summary(
        self,
        text_content: str,
        max_tokens: int = 300
    ) -> str:
        """Generates a concise global or section-level summary for the provided text."""
        pass


class IEmbeddingProvider(ABC):
    """Abstract interface for text embedding generation."""

    @abstractmethod
    async def embed_texts(
        self,
        texts: List[str]
    ) -> List[List[float]]:
        """Generates dense vector embeddings for a batch of text strings."""
        pass


class IVectorStoreAdapter(ABC):
    """Abstract interface for vector database operations."""

    @abstractmethod
    async def upsert_chunks(
        self,
        collection_name: str,
        vectors: List[List[float]],
        payloads: List[Dict[str, Any]],
        embedding_ids: List[UUID]
    ) -> None:
        """Upserts a batch of vectors with corresponding metadata payloads."""
        pass

    @abstractmethod
    async def delete_by_document_id(
        self,
        collection_name: str,
        document_id: UUID
    ) -> None:
        """Deletes all vector points associated with a specific document."""
        pass

from __future__ import annotations

from typing import List, Optional
import logging

from app.rag.embeddings.manager import EmbeddingManager
from app.rag.embeddings.base import EmbeddingProvider, AsyncEmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self):
        self._sync_provider: Optional[EmbeddingProvider] = None
        self._async_provider: Optional[AsyncEmbeddingProvider] = None

    @property
    def sync_provider(self) -> EmbeddingProvider:
        if self._sync_provider is None:
            provider = EmbeddingManager.get_provider(async_mode=False)
            assert isinstance(provider, EmbeddingProvider)
            self._sync_provider = provider
        return self._sync_provider

    @property
    def async_provider(self) -> AsyncEmbeddingProvider:
        if self._async_provider is None:
            provider = EmbeddingManager.get_provider(async_mode=True)
            assert isinstance(provider, AsyncEmbeddingProvider)
            self._async_provider = provider
        return self._async_provider

    def embed_text(self, text: str) -> List[float]:
        return self.sync_provider.embed_text(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return self.sync_provider.embed_texts(texts)

    async def embed_text_async(self, text: str) -> List[float]:
        return await self.async_provider.embed_text(text)

    async def embed_texts_async(self, texts: List[str]) -> List[List[float]]:
        return await self.async_provider.embed_texts(texts)

    @property
    def model_name(self) -> str:
        return self.sync_provider.model_name

    @property
    def dimension(self) -> int:
        return self.sync_provider.dimension
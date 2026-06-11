from __future__ import annotations

from typing import Optional, Union
import logging

from app.config.settings import settings
from app.rag.embeddings.base import EmbeddingProvider, AsyncEmbeddingProvider
from app.rag.embeddings.providers.openai_provider import OpenAIEmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingManager:
    _provider: Optional[EmbeddingProvider] = None
    _async_provider: Optional[AsyncEmbeddingProvider] = None

    @classmethod
    def get_provider(
        cls, async_mode: bool = False
    ) -> Union[EmbeddingProvider, AsyncEmbeddingProvider]:
        provider_name = settings.EMBEDDING_PROVIDER.lower()

        if async_mode:
            if cls._async_provider is not None:
                return cls._async_provider

            logger.info(f"Initializing async embedding provider: {provider_name}")
            if provider_name == "openai":
                from app.rag.embeddings.providers.async_openai_provider import AsyncOpenAIEmbeddingProvider

                cls._async_provider = AsyncOpenAIEmbeddingProvider()
                return cls._async_provider

            raise ValueError(f"Unsupported async embedding provider: {settings.EMBEDDING_PROVIDER}")

        if cls._provider is not None:
            return cls._provider

        logger.info(f"Initializing sync embedding provider: {provider_name}")
        if provider_name == "openai":
            cls._provider = OpenAIEmbeddingProvider()
            return cls._provider

        raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")
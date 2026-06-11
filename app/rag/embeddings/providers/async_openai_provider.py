from __future__ import annotations

from typing import List
import logging

from openai import AsyncOpenAI
from app.rag.embeddings.base import AsyncEmbeddingProvider
from app.config.settings import settings

logger = logging.getLogger(__name__)


class AsyncOpenAIEmbeddingProvider(AsyncEmbeddingProvider):
    """Async OpenAI embedding provider using `AsyncOpenAI` client."""

    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured in settings")
            
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model_name = settings.EMBEDDING_MODEL_NAME
        self._dimension = settings.EMBEDDING_DIMENSION

    async def embed_text(self, text: str) -> List[float]:
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        try:
            response = await self._client.embeddings.create(
                model=self._model_name,
                input=text.strip(),
            )
            return list(response.data[0].embedding)
        except Exception as e:
            logger.error(f"Async OpenAI embedding failed: {str(e)}")
            raise RuntimeError(f"Async OpenAI embedding error: {str(e)}")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            raise ValueError("Texts list cannot be empty")

        try:
            # Sửa lỗi Production: Đảm bảo không có chuỗi rỗng gây crash lỗi 400 Bad Request
            sanitized_texts = [t if (t and t.strip()) else " " for t in texts]

            response = await self._client.embeddings.create(
                model=self._model_name,
                input=sanitized_texts,
            )
            return [list(item.embedding) for item in response.data]
        except Exception as e:
            logger.error(f"Async OpenAI batch embedding failed: {str(e)}")
            raise RuntimeError(f"Async OpenAI batch embedding error: {str(e)}")

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension
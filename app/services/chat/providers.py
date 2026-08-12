from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from openai import AsyncOpenAI

from app.config.settings import settings


@dataclass(frozen=True)
class ChatStreamChunk:
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatCompletionProvider(Protocol):
    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[ChatStreamChunk]:
        ...


class OpenAIChatCompletionProvider:
    def __init__(self, config: dict | None = None):
        user_api_keys = {}
        if config:
            configurable = config.get("configurable", config)
            if isinstance(configurable, dict):
                user_api_keys = configurable.get("user_api_keys") or {}

        # 1. BYOK Path: User has configured their own key
        if "openai" in user_api_keys and user_api_keys["openai"]:
            api_key = user_api_keys["openai"]
            base_url = None
        # 2. Proxy Path (Default): Use platform LiteLLM Proxy
        else:
            api_key = settings.LITELLM_PROXY_KEY
            base_url = settings.LITELLM_PROXY_URL

        if not api_key:
            raise RuntimeError("API key is not configured")

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model_name = settings.CHAT_MODEL_NAME

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[ChatStreamChunk]:
        stream = await self._client.chat.completions.create(
            model=self._model_name,
            messages=messages,
            stream=True,
        )

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage:
                yield ChatStreamChunk(
                    prompt_tokens=usage.prompt_tokens or 0,
                    completion_tokens=usage.completion_tokens or 0,
                )
                continue

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None)
            if content:
                yield ChatStreamChunk(content=content)

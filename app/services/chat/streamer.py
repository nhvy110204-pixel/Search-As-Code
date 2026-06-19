import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone

from app.config.settings import settings
from app.observability.metrics import (
    record_chat_stream_completed,
    record_chat_stream_disconnected,
    record_chat_stream_failed,
)
from app.services.chat.providers import ChatCompletionProvider
from app.services.chat.stream_state import stream_state_manager

logger = logging.getLogger(__name__)


class ChatStreamer:

    def __init__(self, provider: ChatCompletionProvider):
        self.provider = provider

    async def stream_events(
        self,
        messages: list[dict[str, str]],
        assistant_message_id: uuid.UUID,
        is_disconnected: Callable[[], Awaitable[bool]],
        on_chunk: Callable,
        on_complete: Callable,
        on_error: Callable,
        on_timeout: Callable,
        run_id: uuid.UUID | None = None,  # Thêm run_id cho việc kiểm tra cờ hủy từ xa
    ) -> AsyncIterator[dict[str, str]]:
        event_id = 1
        started_at = time.perf_counter()
        first_delta_at: float | None = None
        content_parts: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0

        yield self._create_event(
            event_id,
            "message.created",
            {"message_id": str(assistant_message_id)},
        )
        event_id += 1

        try:
            async for chunk in self._iter_provider_chunks(messages):
                if await is_disconnected():
                    content = "".join(content_parts)
                    on_error("disconnected", "Client disconnected before stream completion")
                    record_chat_stream_disconnected(time.perf_counter() - started_at)
                    return

                # Kiểm tra cờ hủy phân tán từ Redis
                if run_id:
                    if stream_state_manager.is_cancelled(run_id):
                        logger.info(f"Ngắt luồng stream sớm do nhận được tín hiệu hủy: run_id={run_id}")
                        content = "".join(content_parts)
                        on_error("cancelled", "Stream cancelled by user")
                        yield self._create_event(
                            event_id,
                            "error",
                            {
                                "message_id": str(assistant_message_id),
                                "code": "cancelled",
                                "message": "Stream cancelled by user",
                            },
                        )
                        return

                if chunk.prompt_tokens:
                    prompt_tokens = chunk.prompt_tokens
                if chunk.completion_tokens:
                    completion_tokens = chunk.completion_tokens
                if not chunk.content:
                    continue

                if first_delta_at is None:
                    first_delta_at = time.perf_counter()

                content_parts.append(chunk.content)
                if on_chunk:
                    on_chunk(chunk.content)

                yield self._create_event(
                    event_id,
                    "delta",
                    {"message_id": str(assistant_message_id), "content": chunk.content},
                )
                event_id += 1

            content = "".join(content_parts)
            if on_complete:
                on_complete(content, prompt_tokens, completion_tokens, started_at, first_delta_at)
            record_chat_stream_completed(
                time.perf_counter() - started_at,
                (first_delta_at - started_at) if first_delta_at is not None else None,
            )
            yield self._create_event(
                event_id,
                "message.done",
                {
                    "message_id": str(assistant_message_id),
                    "content": content,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            )
        except asyncio.CancelledError:
            content = "".join(content_parts)
            if on_error:
                on_error("disconnected", "Client disconnected before stream completion")
            record_chat_stream_disconnected(time.perf_counter() - started_at)
            raise
        except asyncio.TimeoutError:
            content = "".join(content_parts)
            if on_timeout:
                on_timeout(content, started_at, first_delta_at)
            record_chat_stream_failed(time.perf_counter() - started_at)
            logger.warning("chat stream provider timeout")
            yield self._create_event(
                event_id,
                "error",
                {
                    "message_id": str(assistant_message_id),
                    "code": "provider_timeout",
                    "message": "Chat provider timed out while streaming",
                },
            )
        except Exception as exc:
            content = "".join(content_parts)
            if on_error:
                on_error("provider_error", "Chat provider failed while streaming")
            record_chat_stream_failed(time.perf_counter() - started_at)
            logger.exception("chat stream provider error: %s", exc.__class__.__name__)
            yield self._create_event(
                event_id,
                "error",
                {
                    "message_id": str(assistant_message_id),
                    "code": "provider_error",
                    "message": "Chat provider failed while streaming",
                },
            )

    async def _iter_provider_chunks(self, messages: list[dict[str, str]]):
        iterator = self.provider.stream_chat(messages).__aiter__()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        anext(iterator),
                        timeout=settings.CHAT_PROVIDER_CHUNK_TIMEOUT_SECONDS,
                    )
                    yield chunk
                except StopAsyncIteration:
                    return
        except asyncio.TimeoutError:
            aclose = getattr(iterator, "aclose", None)
            if aclose:
                await aclose()
            raise
        except Exception:
            aclose = getattr(iterator, "aclose", None)
            if aclose:
                await aclose()
            raise
        finally:
            aclose = getattr(iterator, "aclose", None)
            if aclose:
                await aclose()

    def _create_event(self, event_id: int, event: str, data: dict) -> dict[str, str]:
        return {
            "id": str(event_id),
            "event": event,
            "data": json.dumps(data, ensure_ascii=False),
        }

    @staticmethod
    def elapsed_ms(started_at: float, ended_at: float | None = None) -> int:
        return int(((ended_at if ended_at is not None else time.perf_counter()) - started_at) * 1000)

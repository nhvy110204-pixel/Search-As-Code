"""Main chat streaming service - orchestrates all components."""

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings
from app.core.database import SessionLocal
from app.core.logger import service_boundary
from app.models.chat_stream_run import ChatStreamRun
from app.models.user import User
from app.observability.metrics import record_chat_stream_started
from app.repositories.chat_message import ChatMessageRepository
from app.repositories.chat_stream_run import ChatStreamRunRepository
from app.schemas.dto.chat import ChatStreamRequest, PreparedChatStream
from app.services.chat.idempotency import ChatStreamIdempotencyHandler
from app.services.chat.outcome import ChatStreamOutcomeHandler
from app.services.chat.preparer import ChatStreamPreparer
from app.services.chat.providers import ChatCompletionProvider, OpenAIChatCompletionProvider
from app.services.chat.streamer import ChatStreamer
from app.services.chat.validators import ChatStreamValidator
from app.shared.enums import ChatStreamStatus
from blake3 import blake3
from app.services.chat.semantic_cache import semantic_cache
from app.tasks.chat_tasks import save_semantic_cache

logger = logging.getLogger(__name__)


class ChatStreamService:

    def __init__(
        self,
        db: Session,
        provider: ChatCompletionProvider | None = None,
        session_factory: sessionmaker[Session] = SessionLocal,
    ):
        self.db = db
        self.session_factory = session_factory

        if provider is None:
            try:
                self.provider = OpenAIChatCompletionProvider()
            except Exception as exc:
                logger.error("Failed to initialize OpenAI provider: %s", exc)
                raise RuntimeError("Failed to initialize chat provider. Check API key configuration.") from exc
        else:
            self.provider = provider

        self.stream_run_repo = ChatStreamRunRepository(db)
        self.message_repo = ChatMessageRepository(db)

        self.validator = ChatStreamValidator(self.stream_run_repo)
        self.idempotency = ChatStreamIdempotencyHandler(self.stream_run_repo, self.message_repo)
        self.preparer = ChatStreamPreparer(db)
        self.streamer = ChatStreamer(self.provider)
        self.outcome = ChatStreamOutcomeHandler(session_factory, self.stream_run_repo)

    @service_boundary("Prepare Chat Stream")
    async def prepare_stream(self, payload: ChatStreamRequest, user: User) -> PreparedChatStream:
        content = payload.message.strip()
        self.validator.validate_message(content)

        idempotent_run = self.idempotency.get_idempotent_run(user.id, payload.client_request_id)
        if idempotent_run:
            self.idempotency.validate_idempotent_payload(
                idempotent_run,
                payload.session_id,
                payload.parent_id,
                content,
            )
            replay_data = self.idempotency.prepare_idempotent_response(idempotent_run)
            return self._create_prepared_stream_for_replay(
                idempotent_run,
                replay_data,
            )

        self.validator.enforce_rate_limits(user.id)

        # Kiểm tra Semantic Cache (Lock và đọc cache)
        
        query_hash = blake3(content.encode("utf-8")).hexdigest()
        cached_answer, lock_acquired = await semantic_cache.get_or_lock(content)
        
        if cached_answer:
            # Cache Hit: Tạo nhanh tin nhắn ở trạng thái COMPLETED trong DB
            user_message, assistant_message = self.preparer.prepare_messages_for_cache_hit(
                payload.session_id,
                payload.parent_id,
                content,
                user.id,
                cached_answer["content"]
            )
            
            run = self._create_stream_run_for_cache_hit(
                user.id,
                payload.session_id,
                payload.client_request_id,
                user_message.id,
                assistant_message.id,
                content,
                payload.parent_id,
            )
            
            logger.info(
                f"Semantic Cache Hit hoàn tất: session_id={payload.session_id}, user_id={user.id}"
            )
            
            return PreparedChatStream(
                run_id=run.id,
                user_id=user.id,
                session_id=payload.session_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                messages=[],
                client_request_id=payload.client_request_id,
                replay_content=cached_answer["content"],
                replay_prompt_tokens=cached_answer.get("prompt_tokens", 0),
                replay_completion_tokens=cached_answer.get("completion_tokens", 0),
                query_hash=query_hash
            )

        user_message, assistant_message = self.preparer.prepare_messages(
            payload.session_id,
            payload.parent_id,
            content,
            user.id,
        )

        messages = self.preparer.build_provider_messages(payload.session_id, content)

        run = self._create_stream_run(
            user.id,
            payload.session_id,
            payload.client_request_id,
            user_message.id,
            assistant_message.id,
            content,
            payload.parent_id,
        )

        record_chat_stream_started()
        logger.info(
            "chat stream started run_id=%s session_id=%s user_id=%s client_request_id=%s",
            run.id,
            payload.session_id,
            user.id,
            payload.client_request_id,
        )

        return PreparedChatStream(
            run_id=run.id,
            user_id=user.id,
            session_id=payload.session_id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            messages=messages,
            client_request_id=payload.client_request_id,
            query_hash=query_hash if lock_acquired else None
        )

    async def stream_events(
        self,
        prepared: PreparedChatStream,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[dict[str, str]]:
        if prepared.replay_content is not None:
            yield self.streamer._create_event(
                1,
                "message.done",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "content": prepared.replay_content,
                    "prompt_tokens": prepared.replay_prompt_tokens,
                    "completion_tokens": prepared.replay_completion_tokens,
                },
            )
            return

        started_at = None
        content_parts: list[str] = []

        def on_chunk(chunk_content: str):
            content_parts.append(chunk_content)

        def on_complete(content: str, prompt_tokens: int, completion_tokens: int, started_at_: float, first_delta_at: float | None):
            self.outcome.mark_completed(
                prepared,
                content,
                prompt_tokens,
                completion_tokens,
                started_at_,
                first_delta_at,
            )
            # Nếu request này giữ lock ghi cache, gọi Celery task lưu cache dưới nền
            if prepared.query_hash:
                query = prepared.messages[-1]["content"] if prepared.messages else ""
                save_semantic_cache.delay(
                    query=query,
                    content=content,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    query_hash=prepared.query_hash
                )

        def on_error(error_code: str, error_message: str):
            self.outcome.mark_failed(
                prepared,
                "".join(content_parts),
                error_code,
                error_message,
                started_at or 0,
                None,
            )
            # Giải phóng lock nếu luồng sinh bị lỗi
            if prepared.query_hash:
                semantic_cache.release_lock(prepared.query_hash)

        def on_timeout(content: str, started_at_: float, first_delta_at: float | None):
            self.outcome.mark_failed(
                prepared,
                content,
                "provider_timeout",
                "Chat provider timed out while streaming",
                started_at_,
                first_delta_at,
            )
            # Giải phóng lock nếu luồng sinh bị timeout
            if prepared.query_hash:
                semantic_cache.release_lock(prepared.query_hash)

        async for event in self.streamer.stream_events(
            prepared.messages,
            prepared.assistant_message_id,
            is_disconnected,
            on_chunk,
            on_complete,
            on_error,
            on_timeout,
            run_id=prepared.run_id,
        ):
            yield event

    def _create_stream_run(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        client_request_id: str | None,
        user_message_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        content: str,
        parent_id: uuid.UUID | None,
    ) -> ChatStreamRun:
        run = ChatStreamRun(
            user_id=user_id,
            session_id=session_id,
            client_request_id=client_request_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            status=ChatStreamStatus.STREAMING,
            model_name=settings.CHAT_MODEL_NAME,
            metadata_=self.idempotency.create_run_metadata(content, parent_id),
        )
        self.db.add(run)
        self.db.flush()
        self.db.refresh(run)
        return run

    def _create_stream_run_for_cache_hit(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        client_request_id: str | None,
        user_message_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        content: str,
        parent_id: uuid.UUID | None,
    ) -> ChatStreamRun:
        """Tạo đối tượng ChatStreamRun ở trạng thái COMPLETED khi trúng Semantic Cache."""
        run = ChatStreamRun(
            user_id=user_id,
            session_id=session_id,
            client_request_id=client_request_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            status=ChatStreamStatus.COMPLETED,
            model_name=settings.CHAT_MODEL_NAME,
            metadata_=self.idempotency.create_run_metadata(content, parent_id),
            completed_at=datetime.now(timezone.utc),
            duration_ms=0,
        )
        self.db.add(run)
        self.db.flush()
        self.db.refresh(run)
        return run

    def _create_prepared_stream_for_replay(
        self,
        run: ChatStreamRun,
        replay_data: dict,
    ) -> PreparedChatStream:
        return PreparedChatStream(
            run_id=run.id,
            user_id=run.user_id,
            session_id=run.session_id,
            user_message_id=run.user_message_id,
            assistant_message_id=run.assistant_message_id,
            messages=[],
            client_request_id=run.client_request_id,
            replay_content=replay_data.get("replay_content"),
            replay_prompt_tokens=replay_data.get("replay_prompt_tokens", 0),
            replay_completion_tokens=replay_data.get("replay_completion_tokens", 0),
        )

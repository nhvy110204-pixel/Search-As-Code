from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings
from app.core.database import SessionLocal
from app.core.unit_of_work import UnitOfWork
from app.models.chat_message import ChatMessage
from app.models.chat_stream_run import ChatStreamRun
from app.models.user import User
from app.observability.metrics import (
    record_chat_stream_completed,
    record_chat_stream_disconnected,
    record_chat_stream_failed,
    record_chat_stream_started,
)
from app.schemas.dto.chat import ChatStreamRequest
from app.schemas.dto.chat_message import ChatMessageCreate
from app.services.chat.providers import ChatCompletionProvider, OpenAIChatCompletionProvider
from app.shared.enums import ChatStreamStatus, MessageRole, MessageStatus

SYSTEM_PROMPT = "You are RAGFlash, a concise and helpful assistant."
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedChatStream:
    run_id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    messages: list[dict[str, str]]
    client_request_id: str | None = None
    replay_content: str | None = None
    replay_prompt_tokens: int = 0
    replay_completion_tokens: int = 0


class ChatStreamService:
    def __init__(
        self,
        db: Session,
        provider: ChatCompletionProvider | None = None,
        session_factory: sessionmaker[Session] = SessionLocal,
    ):
        self.db = db
        self.provider = provider or OpenAIChatCompletionProvider()
        self.session_factory = session_factory

    def prepare_stream(self, payload: ChatStreamRequest, user: User) -> PreparedChatStream:
        content = payload.message.strip()
        if not content:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Message cannot be empty")
        if len(content) > settings.CHAT_MAX_INPUT_CHARS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Message is too long")

        with UnitOfWork(self.db) as uow:
            chat_session = uow.chat_sessions.get(payload.session_id)
            if not chat_session:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
            if chat_session.user_id != user.id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chat session does not belong to user")

            if payload.parent_id:
                parent = uow.chat_messages.get(payload.parent_id)
                if not parent or parent.session_id != payload.session_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent message is invalid")

            idempotent_run = self._get_idempotent_run(user.id, payload.client_request_id)
            if idempotent_run:
                self._validate_idempotent_payload(idempotent_run, payload, content)
                return self._prepare_idempotent_response(idempotent_run)

            self._enforce_stream_limits(user.id)

            history = self._load_recent_history(payload.session_id)

            user_message = uow.chat_messages.create(
                ChatMessageCreate(
                    session_id=payload.session_id,
                    parent_id=payload.parent_id,
                    role=MessageRole.USER,
                    content=content,
                )
            )
            uow.chat_messages.update(user_message, {"status": MessageStatus.COMPLETED})

            assistant_message = uow.chat_messages.create(
                ChatMessageCreate(
                    session_id=payload.session_id,
                    parent_id=user_message.id,
                    role=MessageRole.ASSISTANT,
                    content="",
                )
            )
            uow.chat_messages.update(assistant_message, {"status": MessageStatus.STREAMING})

            run = ChatStreamRun(
                user_id=user.id,
                session_id=payload.session_id,
                client_request_id=payload.client_request_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                status=ChatStreamStatus.STREAMING,
                model_name=settings.CHAT_MODEL_NAME,
                metadata_={
                    "message_sha256": self._message_hash(content),
                    "parent_id": str(payload.parent_id) if payload.parent_id else None,
                },
            )
            self.db.add(run)
            self.db.flush()
            self.db.refresh(run)

            messages = self._build_provider_messages(history, content)
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
            )

    async def stream_events(
        self,
        prepared: PreparedChatStream,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[dict[str, str]]:
        event_id = 1
        started_at = time.perf_counter()
        first_delta_at: float | None = None
        content_parts: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0

        yield self._event(
            event_id,
            "message.created",
            {
                "session_id": str(prepared.session_id),
                "user_message_id": str(prepared.user_message_id),
                "assistant_message_id": str(prepared.assistant_message_id),
            },
        )
        event_id += 1

        if prepared.replay_content is not None:
            yield self._event(
                event_id,
                "message.done",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "content": prepared.replay_content,
                    "prompt_tokens": prepared.replay_prompt_tokens,
                    "completion_tokens": prepared.replay_completion_tokens,
                },
            )
            return

        try:
            async for chunk in self._iter_provider_chunks(prepared.messages):
                if await is_disconnected():
                    self._mark_disconnected(prepared, "".join(content_parts), started_at, first_delta_at)
                    record_chat_stream_disconnected(time.perf_counter() - started_at)
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
                yield self._event(
                    event_id,
                    "delta",
                    {"message_id": str(prepared.assistant_message_id), "content": chunk.content},
                )
                event_id += 1

            content = "".join(content_parts)
            self._mark_completed(prepared, content, prompt_tokens, completion_tokens, started_at, first_delta_at)
            record_chat_stream_completed(
                time.perf_counter() - started_at,
                (first_delta_at - started_at) if first_delta_at is not None else None,
            )
            yield self._event(
                event_id,
                "message.done",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "content": content,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            )
        except asyncio.CancelledError:
            self._mark_disconnected(prepared, "".join(content_parts), started_at, first_delta_at)
            record_chat_stream_disconnected(time.perf_counter() - started_at)
            raise
        except asyncio.TimeoutError:
            self._mark_failed(
                prepared,
                "".join(content_parts),
                "provider_timeout",
                "Chat provider did not send data within the configured timeout",
                started_at,
                first_delta_at,
            )
            record_chat_stream_failed(time.perf_counter() - started_at)
            logger.warning(
                "chat stream provider timeout run_id=%s session_id=%s user_id=%s",
                prepared.run_id,
                prepared.session_id,
                prepared.user_id,
            )
            yield self._event(
                event_id,
                "error",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "code": "provider_timeout",
                    "message": "Chat provider timed out while streaming",
                },
            )
        except Exception as exc:
            self._mark_failed(
                prepared,
                "".join(content_parts),
                "provider_error",
                "Chat provider failed while streaming",
                started_at,
                first_delta_at,
            )
            record_chat_stream_failed(time.perf_counter() - started_at)
            logger.exception(
                "chat stream provider error run_id=%s session_id=%s user_id=%s error_type=%s",
                prepared.run_id,
                prepared.session_id,
                prepared.user_id,
                exc.__class__.__name__,
            )
            yield self._event(
                event_id,
                "error",
                {
                    "message_id": str(prepared.assistant_message_id),
                    "code": "provider_error",
                    "message": "Chat provider failed while streaming",
                },
            )

    async def _iter_provider_chunks(self, messages: list[dict[str, str]]):
        iterator = self.provider.stream_chat(messages).__aiter__()
        try:
            while True:
                try:
                    yield await asyncio.wait_for(
                        anext(iterator),
                        timeout=settings.CHAT_PROVIDER_CHUNK_TIMEOUT_SECONDS,
                    )
                except StopAsyncIteration:
                    return
        except asyncio.TimeoutError:
            aclose = getattr(iterator, "aclose", None)
            if aclose:
                await aclose()
            raise

    def _load_recent_history(self, session_id: uuid.UUID) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.is_deleted == False,
                ChatMessage.status == MessageStatus.COMPLETED,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(settings.CHAT_HISTORY_LIMIT)
        )
        messages = self.db.execute(stmt).scalars().all()
        return list(reversed(messages))

    def _build_provider_messages(self, history: list[ChatMessage], current_message: str) -> list[dict[str, str]]:
        messages = [{"role": MessageRole.SYSTEM.value, "content": SYSTEM_PROMPT}]
        budget_used = len(SYSTEM_PROMPT) + len(current_message)
        selected_history: list[ChatMessage] = []
        for message in history:
            if message.role in {MessageRole.USER, MessageRole.ASSISTANT, MessageRole.SYSTEM, MessageRole.TOOL}:
                next_size = len(message.content or "")
                if budget_used + next_size > settings.CHAT_HISTORY_MAX_CHARS:
                    continue
                budget_used += next_size
                selected_history.append(message)
        for message in selected_history:
            messages.append({"role": message.role.value, "content": message.content})
        messages.append({"role": MessageRole.USER.value, "content": current_message})
        return messages

    def _mark_completed(
        self,
        prepared: PreparedChatStream,
        content: str,
        prompt_tokens: int,
        completion_tokens: int,
        started_at: float,
        first_delta_at: float | None,
    ) -> None:
        self._update_outcome(
            prepared,
            message_values={
                "content": content,
                "status": MessageStatus.COMPLETED,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
            run_values={
                "status": ChatStreamStatus.COMPLETED,
                "completed_at": datetime.now(timezone.utc),
                "duration_ms": self._elapsed_ms(started_at),
                "time_to_first_delta_ms": self._elapsed_ms(started_at, first_delta_at) if first_delta_at else 0,
                "error_code": None,
                "error_message": None,
            },
        )
        logger.info(
            "chat stream completed run_id=%s session_id=%s user_id=%s duration_ms=%s",
            prepared.run_id,
            prepared.session_id,
            prepared.user_id,
            self._elapsed_ms(started_at),
        )

    def _mark_failed(
        self,
        prepared: PreparedChatStream,
        content: str,
        error_code: str,
        error_message: str,
        started_at: float,
        first_delta_at: float | None,
    ) -> None:
        self._update_outcome(
            prepared,
            message_values={"content": content, "status": MessageStatus.FAILED},
            run_values={
                "status": ChatStreamStatus.FAILED,
                "error_code": error_code,
                "error_message": error_message[:500],
                "completed_at": datetime.now(timezone.utc),
                "duration_ms": self._elapsed_ms(started_at),
                "time_to_first_delta_ms": self._elapsed_ms(started_at, first_delta_at) if first_delta_at else 0,
            },
        )

    def _mark_disconnected(
        self,
        prepared: PreparedChatStream,
        content: str,
        started_at: float,
        first_delta_at: float | None,
    ) -> None:
        self._update_outcome(
            prepared,
            message_values={"content": content, "status": MessageStatus.FAILED},
            run_values={
                "status": ChatStreamStatus.DISCONNECTED,
                "error_code": "disconnected",
                "error_message": "Client disconnected before stream completion",
                "completed_at": datetime.now(timezone.utc),
                "duration_ms": self._elapsed_ms(started_at),
                "time_to_first_delta_ms": self._elapsed_ms(started_at, first_delta_at) if first_delta_at else 0,
            },
        )
        logger.info(
            "chat stream disconnected run_id=%s session_id=%s user_id=%s duration_ms=%s",
            prepared.run_id,
            prepared.session_id,
            prepared.user_id,
            self._elapsed_ms(started_at),
        )

    def _update_outcome(self, prepared: PreparedChatStream, message_values: dict, run_values: dict) -> None:
        db = self.session_factory()
        try:
            with UnitOfWork(db) as uow:
                message = uow.chat_messages.get(prepared.assistant_message_id)
                if message:
                    uow.chat_messages.update(message, message_values)
                run = db.get(ChatStreamRun, prepared.run_id)
                if run:
                    for key, value in run_values.items():
                        setattr(run, key, value)
                    db.add(run)
                    db.flush()
        finally:
            db.close()

    def _get_idempotent_run(self, user_id: uuid.UUID, client_request_id: str | None) -> ChatStreamRun | None:
        if not client_request_id:
            return None
        stmt = select(ChatStreamRun).where(
            ChatStreamRun.user_id == user_id,
            ChatStreamRun.client_request_id == client_request_id,
            ChatStreamRun.is_deleted == False,
        )
        return self.db.execute(stmt).scalars().first()

    def _prepare_idempotent_response(self, run: ChatStreamRun) -> PreparedChatStream:
        if run.status == ChatStreamStatus.COMPLETED and run.user_message_id and run.assistant_message_id:
            assistant_message = self.db.get(ChatMessage, run.assistant_message_id)
            if assistant_message:
                return PreparedChatStream(
                    run_id=run.id,
                    user_id=run.user_id,
                    session_id=run.session_id,
                    user_message_id=run.user_message_id,
                    assistant_message_id=run.assistant_message_id,
                    messages=[],
                    client_request_id=run.client_request_id,
                    replay_content=assistant_message.content,
                    replay_prompt_tokens=assistant_message.prompt_tokens,
                    replay_completion_tokens=assistant_message.completion_tokens,
                )
        if run.status in {ChatStreamStatus.STARTED, ChatStreamStatus.STREAMING}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chat stream request is already running")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chat stream request was already used")

    def _validate_idempotent_payload(self, run: ChatStreamRun, payload: ChatStreamRequest, content: str) -> None:
        metadata = run.metadata_ or {}
        expected_parent_id = str(payload.parent_id) if payload.parent_id else None
        if (
            run.session_id != payload.session_id
            or metadata.get("message_sha256") != self._message_hash(content)
            or metadata.get("parent_id") != expected_parent_id
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key was used with a different request")

    def _enforce_stream_limits(self, user_id: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        one_minute_ago = now - timedelta(minutes=1)
        one_day_ago = now - timedelta(days=1)

        active_count = self._count_user_runs(
            user_id,
            statuses={ChatStreamStatus.STARTED, ChatStreamStatus.STREAMING},
        )
        if active_count >= settings.CHAT_STREAM_CONCURRENT_LIMIT:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many active chat streams")

        minute_count = self._count_user_runs(user_id, created_after=one_minute_ago)
        if minute_count >= settings.CHAT_STREAM_RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Chat stream rate limit exceeded")

        daily_count = self._count_user_runs(user_id, created_after=one_day_ago)
        if daily_count >= settings.CHAT_STREAM_DAILY_LIMIT:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Daily chat stream quota exceeded")

    def _count_user_runs(
        self,
        user_id: uuid.UUID,
        created_after: datetime | None = None,
        statuses: set[ChatStreamStatus] | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(ChatStreamRun).where(
            ChatStreamRun.user_id == user_id,
            ChatStreamRun.is_deleted == False,
        )
        if created_after is not None:
            stmt = stmt.where(ChatStreamRun.created_at >= created_after)
        if statuses:
            stmt = stmt.where(ChatStreamRun.status.in_([status.value for status in statuses]))
        return self.db.execute(stmt).scalar() or 0

    def _elapsed_ms(self, started_at: float, ended_at: float | None = None) -> int:
        return int(((ended_at if ended_at is not None else time.perf_counter()) - started_at) * 1000)

    def _message_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _event(self, event_id: int, event: str, data: dict) -> dict[str, str]:
        return {
            "id": str(event_id),
            "event": event,
            "data": json.dumps(data, ensure_ascii=False),
        }

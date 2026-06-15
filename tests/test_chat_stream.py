import asyncio
import json
import uuid

import pytest

from app.config.settings import settings
from app.core.security import create_access_token, decode_access_token
from app.models.chat_stream_run import ChatStreamRun
from app.schemas.dto.chat import ChatStreamRequest, PreparedChatStream
from app.services.chat.idempotency import ChatStreamIdempotencyHandler
from app.services.chat.providers import ChatStreamChunk
from app.services.chat.stream import ChatStreamService
from app.services.chat.streamer import ChatStreamer
from app.shared.enums import ChatStreamStatus


class FakeProvider:
    async def stream_chat(self, messages):
        yield ChatStreamChunk(content="Hello")
        yield ChatStreamChunk(content=" world")
        yield ChatStreamChunk(prompt_tokens=3, completion_tokens=2)


class FailingProvider:
    async def stream_chat(self, messages):
        yield ChatStreamChunk(content="partial")
        raise RuntimeError("provider failed")


class SlowProvider:
    async def stream_chat(self, messages):
        await asyncio.sleep(1)
        yield ChatStreamChunk(content="late")


async def _collect_events(streamer):
    prepared = PreparedChatStream(
        run_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        user_message_id=uuid.uuid4(),
        assistant_message_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "Hi"}],
    )

    async def is_disconnected():
        return False

    return [event async for event in streamer.stream_events(
        prepared.messages,
        prepared.assistant_message_id,
        is_disconnected,
        None,
        None,
        None,
        None,
    )]


def _event_data(event):
    return json.loads(event["data"])


def test_stream_events_emit_created_deltas_and_done():
    streamer = ChatStreamer(FakeProvider())
    events = asyncio.run(_collect_events(streamer))

    assert [event["event"] for event in events] == ["message.created", "delta", "delta", "message.done"]
    assert _event_data(events[1])["content"] == "Hello"
    assert _event_data(events[2])["content"] == " world"
    assert _event_data(events[3])["content"] == "Hello world"
    assert _event_data(events[3])["prompt_tokens"] == 3
    assert _event_data(events[3])["completion_tokens"] == 2


def test_stream_events_emit_error_and_mark_failed():
    streamer = ChatStreamer(FailingProvider())
    events = asyncio.run(_collect_events(streamer))

    assert [event["event"] for event in events] == ["message.created", "delta", "error"]
    assert _event_data(events[2])["code"] == "provider_error"


def test_stream_events_emit_timeout_error(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_PROVIDER_CHUNK_TIMEOUT_SECONDS", 0.01)
    streamer = ChatStreamer(SlowProvider())
    events = asyncio.run(_collect_events(streamer))

    assert [event["event"] for event in events] == ["message.created", "error"]
    assert _event_data(events[1])["code"] == "provider_timeout"


def test_idempotency_rejects_different_payload():
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    handler = ChatStreamIdempotencyHandler(stream_run_repo=None, message_repo=None)
    original_message = "same key original"
    run = ChatStreamRun(
        id=uuid.uuid4(),
        user_id=user_id,
        session_id=session_id,
        client_request_id="req-1",
        status=ChatStreamStatus.COMPLETED,
        model_name=settings.CHAT_MODEL_NAME,
        metadata_={"message_sha256": handler._hash_content(original_message), "parent_id": None},
    )

    with pytest.raises(Exception):
        handler.validate_idempotent_payload(
            run,
            session_id,
            None,
            "different",
        )


def test_decode_access_token_accepts_sub_uuid():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)

    assert decode_access_token(token) == user_id


def test_decode_access_token_rejects_invalid_token():
    with pytest.raises(Exception):
        decode_access_token("not-a-token")

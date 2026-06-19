import uuid
import pytest
from unittest.mock import MagicMock
from app.services.core.redis_service import RedisCacheService, CachedChatMessage
from app.shared.enums import MessageRole, MessageStatus


class MockRedis:
    def __init__(self, **kwargs):
        self.store = {}
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl

    def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0


class DummyMessage:
    def __init__(self, role, content):
        self.role = role
        self.content = content


def test_redis_cache_service_flow():
    mock_client = MockRedis()
    service = RedisCacheService(redis_client=mock_client)
    session_id = uuid.uuid4()

    # 1. Cache Miss
    assert service.get_cached_history(session_id) is None

    # 2. Set Cache
    history = [
        DummyMessage(MessageRole.USER, "Hello"),
        DummyMessage(MessageRole.ASSISTANT, "Hi there!"),
    ]
    service.set_cached_history(session_id, history, ttl=100)

    # Verify storage contents
    cached_key = service._get_key(session_id)
    assert cached_key in mock_client.store
    assert mock_client.ttls[cached_key] == 100

    # 3. Cache Hit
    cached_history = service.get_cached_history(session_id)
    assert cached_history is not None
    assert len(cached_history) == 2
    assert cached_history[0].role == MessageRole.USER
    assert cached_history[0].content == "Hello"
    assert cached_history[1].role == MessageRole.ASSISTANT
    assert cached_history[1].content == "Hi there!"

    # 4. Invalidate Cache
    service.invalidate_history(session_id)
    assert service.get_cached_history(session_id) is None

import uuid
import json
import asyncio
import pytest
from unittest.mock import MagicMock, patch
from app.services.chat.streamer import ChatStreamer
from app.services.chat.stream_state import stream_state_manager
from app.services.chat.providers import ChatStreamChunk

# Thiết lập Mock Redis cục bộ cho kiểm thử
class MockRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl
        return True

    def exists(self, key):
        return 1 if key in self.store else 0

    def delete(self, key):
        if key in self.store:
            del self.store[key]
            if key in self.ttls:
                del self.ttls[key]
            return 1
        return 0


class FakeSlowProvider:
    """Giả lập provider trả về các chunk chậm rãi để có thể xen lệnh hủy."""
    async def stream_chat(self, messages):
        yield ChatStreamChunk(content="Bắt đầu ")
        await asyncio.sleep(0.1)
        yield ChatStreamChunk(content="sinh ")
        await asyncio.sleep(0.1)
        yield ChatStreamChunk(content="văn bản...")


def test_distributed_stream_cancellation_flow():
    """
    Kiểm nghiệm toàn bộ luồng hủy stream phân tán.
    """
    mock_redis = MockRedis()

    with patch("app.services.core.redis_service.redis_cache_service.redis", mock_redis):
        # 1. Đặt cờ hủy thông qua manager
        run_id = uuid.uuid4()
        assert not stream_state_manager.is_cancelled(run_id)

        stream_state_manager.flag_cancellation(run_id)
        assert stream_state_manager.is_cancelled(run_id)

        # 2. Xóa cờ hủy
        mock_redis.delete(f"stream_cancel:{run_id}")
        assert not stream_state_manager.is_cancelled(run_id)


def test_streamer_aborts_early_on_cancel_flag():
    """
    Kiểm tra xem ChatStreamer có ngắt giữa chừng và bắn ra sự kiện error
    khi phát hiện cờ hủy trên Redis hay không.
    """
    mock_redis = MockRedis()
    streamer = ChatStreamer(FakeSlowProvider())
    run_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()

    async def is_disconnected():
        return False

    # Định nghĩa các callbacks trống
    on_chunk = MagicMock()
    on_complete = MagicMock()
    on_error = MagicMock()
    on_timeout = MagicMock()

    async def run_test():
        # Giả lập việc phát hiện hủy sau chunk thứ 1 (hoặc đặt cờ hủy giữa chừng sau 0.05s)
        async def cancel_midway():
            await asyncio.sleep(0.05)
            stream_state_manager.flag_cancellation(run_id)

        # Trình đọc luồng SSE
        async def read_stream():
            events = []
            async for event in streamer.stream_events(
                messages=[],
                assistant_message_id=assistant_message_id,
                is_disconnected=is_disconnected,
                on_chunk=on_chunk,
                on_complete=on_complete,
                on_error=on_error,
                on_timeout=on_timeout,
                run_id=run_id
            ):
                events.append(event)
            return events

        # Chạy song song cả hai tiến trình
        results = await asyncio.gather(
            cancel_midway(),
            read_stream()
        )
        return results[1]

    with patch("app.services.core.redis_service.redis_cache_service.redis", mock_redis):
        events = asyncio.run(run_test())

        # Kiểm chứng streamer đã bị hủy và bắn ra sự kiện error tương ứng
        event_names = [e["event"] for e in events]
        assert "message.created" in event_names
        assert "delta" in event_names
        assert "error" in event_names
        
        # Đảm bảo không kết thúc thành công (không có message.done)
        assert "message.done" not in event_names

        # Xác minh callback on_error đã được kích hoạt đúng với mã 'cancelled'
        on_error.assert_called_once_with("cancelled", "Stream cancelled by user")

        # Phân tích cú pháp dữ liệu sự kiện lỗi
        error_event = [e for e in events if e["event"] == "error"][0]
        data = json.loads(error_event["data"])
        assert data["code"] == "cancelled"
        assert data["message"] == "Stream cancelled by user"

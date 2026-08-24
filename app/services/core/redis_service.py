import json
import logging
import uuid
from typing import Optional, List, Any
import redis
from app.config.settings import settings
from app.shared.enums import MessageRole

logger = logging.getLogger(__name__)


class CachedChatMessage:
    """Rút gọn tin nhắn chat để lưu trữ/truy xuất bộ nhớ đệm (cache)."""
    def __init__(self, role: str, content: str):
        self._role = role
        self.content = content

    @property
    def role(self):
        if isinstance(self._role, MessageRole):
            return self._role
        try:
            return MessageRole(self._role)
        except ValueError:
            return MessageRole.USER


class RedisCacheService:
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        if redis_client is None:
            try:
                redis_client = redis.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
            except Exception as e:
                logger.error(f"Khởi tạo client Redis thất bại: {e}")
        self.redis = redis_client

    def _get_key(self, session_id: uuid.UUID) -> str:
        return f"chat_history:session:{session_id}"

    def get_cached_history(self, session_id: uuid.UUID) -> Optional[List[CachedChatMessage]]:
        """Lấy lịch sử chat gần đây từ Redis, trả về None nếu không tìm thấy cache (miss) hoặc xảy ra lỗi."""
        if not self.redis:
            return None
        key = self._get_key(session_id)
        try:
            data = self.redis.get(key)
            if data:
                raw_messages = json.loads(data)
                logger.info(f"Tìm thấy dữ liệu trong cache (Cache HIT) cho session_id={session_id}")
                return [CachedChatMessage(m["role"], m["content"]) for m in raw_messages]
            logger.info(f"Không tìm thấy dữ liệu trong cache (Cache MISS) cho session_id={session_id}")
        except redis.RedisError as e:
            logger.error(f"Lỗi Redis trong quá trình lấy dữ liệu lịch sử đã cache (get_cached_history): {e}")
        except Exception as e:
            logger.error(f"Lỗi không xác định trong quá trình lấy dữ liệu lịch sử đã cache (get_cached_history): {e}")
        return None

    def set_cached_history(self, session_id: uuid.UUID, history: List[Any], ttl: int = 43200) -> None:
        """Lưu lịch sử chat gần đây vào Redis với thời gian sống TTL (mặc định 12 giờ)."""
        if not self.redis:
            return
        key = self._get_key(session_id)
        try:
            serialized = []
            for msg in history:
                role_val = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
                serialized.append({
                    "role": role_val,
                    "content": msg.content or ""
                })
            self.redis.setex(key, ttl, json.dumps(serialized))
            logger.info(f"Lưu lịch sử vào cache thành công cho session_id={session_id} (TTL={ttl}s)")
        except redis.RedisError as e:
            logger.error(f"Lỗi Redis trong quá trình lưu lịch sử vào cache (set_cached_history): {e}")
        except Exception as e:
            logger.error(f"Lỗi không xác định trong quá trình lưu lịch sử vào cache (set_cached_history): {e}")

    def invalidate_history(self, session_id: uuid.UUID) -> None:
        """Xóa bỏ/hủy lịch sử đã lưu trong cache cho một session."""
        if not self.redis:
            return
        key = self._get_key(session_id)
        try:
            self.redis.delete(key)
            logger.info(f"Đã hủy cache Redis cho session_id={session_id}")
        except redis.RedisError as e:
            logger.error(f"Lỗi Redis trong quá trình hủy cache (invalidate_history): {e}")
        except Exception as e:
            logger.error(f"Lỗi không xác định trong quá trình hủy cache (invalidate_history): {e}")

    def publish_ingestion_event(self, project_id: str | uuid.UUID, event_data: dict) -> None:
        """Phát sự kiện tiến trình Ingestion qua Redis Pub/Sub và lưu snapshot mới nhất."""
        if not self.redis:
            return
        try:
            channel = f"ingestion:project:{str(project_id)}"
            payload = json.dumps(event_data, default=str)
            self.redis.publish(channel, payload)

            task_id = event_data.get("task_id")
            if task_id:
                snap_key = f"ingestion:task:{task_id}:snapshot"
                self.redis.setex(snap_key, 3600, payload)
        except Exception as e:
            logger.debug(f"Không thể publish ingestion event lên Redis: {e}")

    def get_ingestion_snapshot(self, task_id: str | uuid.UUID) -> Optional[dict]:
        """Đọc snapshot tiến trình mới nhất từ Redis cache (sub-millisecond)."""
        if not self.redis:
            return None
        try:
            snap_key = f"ingestion:task:{str(task_id)}:snapshot"
            raw = self.redis.get(snap_key)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug(f"Không thể đọc snapshot ingestion từ Redis: {e}")
        return None

    def get_pubsub(self):
        """Khởi tạo PubSub listener từ Redis client."""
        if not self.redis:
            return None
        return self.redis.pubsub()


redis_cache_service = RedisCacheService()
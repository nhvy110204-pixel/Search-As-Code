import logging
import uuid
from app.services.core.redis_service import redis_cache_service

logger = logging.getLogger(__name__)


class RedisStreamStateManager:
    """Quản lý trạng thái hủy luồng stream phân tán bằng Redis."""

    def __init__(self, ttl: int = 300):
        self.ttl = ttl  # Thời gian sống của cờ hủy (mặc định 5 phút)

    def flag_cancellation(self, run_id: uuid.UUID) -> None:
        """
        Đánh dấu hủy luồng stream bằng cách đặt một khóa trên Redis.
        """
        if not redis_cache_service.redis:
            logger.warning("Không thể đặt cờ hủy vì Redis không hoạt động.")
            return

        cancel_key = f"stream_cancel:{run_id}"
        try:
            # Đặt cờ hủy với TTL để tránh rác Redis
            redis_cache_service.redis.setex(cancel_key, self.ttl, "1")
            logger.info(f"Đã đặt cờ hủy cho luồng stream: key={cancel_key}")
        except Exception as e:
            logger.error(f"Lỗi khi đặt cờ hủy cho run_id={run_id}: {e}")

    def is_cancelled(self, run_id: uuid.UUID) -> bool:
        """
        Kiểm tra xem luồng stream có nhận được yêu cầu hủy từ người dùng không.
        """
        if not redis_cache_service.redis:
            return False

        cancel_key = f"stream_cancel:{run_id}"
        try:
            cancelled = redis_cache_service.redis.exists(cancel_key) == 1
            if cancelled:
                logger.info(f"Phát hiện yêu cầu hủy cho luồng stream: key={cancel_key}")
            return cancelled
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra cờ hủy cho run_id={run_id}: {e}")
            return False


stream_state_manager = RedisStreamStateManager()

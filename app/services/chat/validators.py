import uuid
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.config.settings import settings
from app.repositories.chat_stream_run import ChatStreamRunRepository
from app.shared.enums import ChatStreamStatus
from app.services.core.redis_service import redis_cache_service

logger = logging.getLogger(__name__)


class ChatStreamValidator:

    def __init__(self, stream_run_repo: ChatStreamRunRepository):
        self.stream_run_repo = stream_run_repo

    def validate_message(self, content: str) -> None:
        content = content.strip()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Message cannot be empty"
            )
        if len(content) > settings.CHAT_MAX_INPUT_CHARS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Message is too long"
            )

    def enforce_rate_limits(self, user_id: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()

        try:
            r = redis_cache_service.redis
            if r is None:
                raise RuntimeError("Redis client is not available")

            # 1. Concurrent Limits
            active_key = f"chat:active:{user_id}"
            r.zremrangebyscore(active_key, 0, now_ts)
            active_count = r.zcard(active_key)
            if active_count >= settings.CHAT_STREAM_CONCURRENT_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many active chat streams"
                )

            # 2. Minute Rate Limits
            minute_key = f"chat:minute:{user_id}"
            one_minute_ago_ts = (now - timedelta(minutes=1)).timestamp()
            r.zremrangebyscore(minute_key, 0, one_minute_ago_ts)
            minute_count = r.zcard(minute_key)
            if minute_count >= settings.CHAT_STREAM_RATE_LIMIT_PER_MINUTE:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Chat stream rate limit exceeded"
                )

            # 3. Daily Rate Limits
            daily_key = f"chat:daily:{user_id}"
            one_day_ago_ts = (now - timedelta(days=1)).timestamp()
            r.zremrangebyscore(daily_key, 0, one_day_ago_ts)
            daily_count = r.zcard(daily_key)
            if daily_count >= settings.CHAT_STREAM_DAILY_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Daily chat stream quota exceeded"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.warning(
                "Redis rate limiter failed: %s. Falling back to PostgreSQL DB rate limiter.",
                e,
                exc_info=True
            )
            self._enforce_rate_limits_db_fallback(user_id)

    def _enforce_rate_limits_db_fallback(self, user_id: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        one_minute_ago = now - timedelta(minutes=1)
        one_day_ago = now - timedelta(days=1)

        active_count = self.stream_run_repo.count_user_runs(
            user_id,
            statuses={ChatStreamStatus.STARTED, ChatStreamStatus.STREAMING},
        )
        if active_count >= settings.CHAT_STREAM_CONCURRENT_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many active chat streams"
            )

        minute_count = self.stream_run_repo.count_user_runs(user_id, created_after=one_minute_ago)
        if minute_count >= settings.CHAT_STREAM_RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Chat stream rate limit exceeded"
            )

        daily_count = self.stream_run_repo.count_user_runs(user_id, created_after=one_day_ago)
        if daily_count >= settings.CHAT_STREAM_DAILY_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Daily chat stream quota exceeded"
            )

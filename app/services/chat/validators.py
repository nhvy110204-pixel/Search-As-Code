import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.config.settings import settings
from app.repositories.chat_stream_run import ChatStreamRunRepository
from app.shared.enums import ChatStreamStatus


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

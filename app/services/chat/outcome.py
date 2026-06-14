"""Outcome handling for chat streaming - updating run/message status."""

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from app.core.unit_of_work import UnitOfWork
from app.repositories.chat_stream_run import ChatStreamRunRepository
from app.shared.enums import ChatStreamStatus, MessageStatus

if TYPE_CHECKING:
    from app.schemas.dto.chat import PreparedChatStream

logger = logging.getLogger(__name__)


class ChatStreamOutcomeHandler:

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        stream_run_repo: ChatStreamRunRepository,
    ):
        self.session_factory = session_factory
        self.stream_run_repo = stream_run_repo

    def mark_completed(
        self,
        prepared: "PreparedChatStream",
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

    def mark_failed(
        self,
        prepared: "PreparedChatStream",
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

    def mark_disconnected(
        self,
        prepared: "PreparedChatStream",
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

    def _update_outcome(
        self,
        prepared: "PreparedChatStream",
        message_values: dict,
        run_values: dict,
    ) -> None:
        db = self.session_factory()
        try:
            with UnitOfWork(db) as uow:
                message = uow.chat_messages.get(prepared.assistant_message_id)
                if message:
                    uow.chat_messages.update(message, message_values)
                run = self.stream_run_repo.get(prepared.run_id)
                if run:
                    self.stream_run_repo.update(run, run_values)
        finally:
            db.close()

    @staticmethod
    def _elapsed_ms(started_at: float, ended_at: float | None = None) -> int:
        return int(((ended_at if ended_at is not None else time.perf_counter()) - started_at) * 1000)

"""Idempotency handling for chat streaming."""

import hashlib
import uuid

from fastapi import HTTPException, status

from app.models.chat_stream_run import ChatStreamRun
from app.repositories.chat_stream_run import ChatStreamRunRepository
from app.shared.enums import ChatStreamStatus


class ChatStreamIdempotencyHandler:

    def __init__(self, stream_run_repo: ChatStreamRunRepository, message_repo):
        self.stream_run_repo = stream_run_repo
        self.message_repo = message_repo

    def get_idempotent_run(
        self,
        user_id: uuid.UUID,
        client_request_id: str | None,
    ) -> ChatStreamRun | None:
        if not client_request_id:
            return None
        return self.stream_run_repo.get_by_user_and_client_request_id(user_id, client_request_id)

    def validate_idempotent_payload(
        self,
        run: ChatStreamRun,
        session_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        content: str,
    ) -> None:
        metadata = run.metadata_ or {}
        expected_parent_id = str(parent_id) if parent_id else None
        if (
            run.session_id != session_id
            or metadata.get("message_sha256") != self._hash_content(content)
            or metadata.get("parent_id") != expected_parent_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was used with a different request"
            )

    def prepare_idempotent_response(
        self,
        run: ChatStreamRun,
    ) -> dict:
        if run.status == ChatStreamStatus.COMPLETED and run.user_message_id and run.assistant_message_id:
            assistant_message = self.message_repo.get(run.assistant_message_id)
            if assistant_message:
                return {
                    "replay_content": assistant_message.content,
                    "replay_prompt_tokens": assistant_message.prompt_tokens,
                    "replay_completion_tokens": assistant_message.completion_tokens,
                }
        if run.status in {ChatStreamStatus.STARTED, ChatStreamStatus.STREAMING}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Chat stream request is already running"
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chat stream request was already used"
        )

    def create_run_metadata(
        self,
        content: str,
        parent_id: uuid.UUID | None,
    ) -> dict:
        return {
            "message_sha256": self._hash_content(content),
            "parent_id": str(parent_id) if parent_id else None,
        }

    def _hash_content(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

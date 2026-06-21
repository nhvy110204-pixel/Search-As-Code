from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies.auth import get_current_user
from app.config.settings import settings
from app.core.database import SessionLocal, get_db
from app.models.user import User
from app.schemas.dto.chat import ChatStreamRequest
from app.services.chat.providers import ChatCompletionProvider, OpenAIChatCompletionProvider
from app.services.chat.stream import ChatStreamService
from app.services.chat.stream_state import stream_state_manager

router = APIRouter(prefix="/chat", tags=["Chat"])


def get_chat_completion_provider() -> ChatCompletionProvider:
    try:
        return OpenAIChatCompletionProvider()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


def get_chat_stream_service(
    db: Session = Depends(get_db),
    provider: ChatCompletionProvider = Depends(get_chat_completion_provider),
) -> ChatStreamService:
    return ChatStreamService(
        db=db,
        provider=provider,
        session_factory=SessionLocal,
    )


@router.post("/stream")
async def stream_chat(
    payload: ChatStreamRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: ChatStreamService = Depends(get_chat_stream_service),
):
    prepared = await service.prepare_stream(payload, current_user)

    return EventSourceResponse(
        service.stream_events(prepared, request.is_disconnected),
        ping=settings.CHAT_STREAM_PING_SECONDS,
        send_timeout=settings.CHAT_STREAM_SEND_TIMEOUT_SECONDS,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



@router.post("/stream/{run_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_chat_stream(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    """
    Đánh dấu hủy một luồng stream đang hoạt động từ xa (phân tán).
    """
    stream_state_manager.flag_cancellation(run_id)

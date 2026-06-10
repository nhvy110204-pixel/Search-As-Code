from __future__ import annotations

import uuid
from typing import Optional, TYPE_CHECKING
from sqlalchemy import ARRAY, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import AIEntityMixin, Base

if TYPE_CHECKING:
    from .chat_session import ChatSession
    from .sac_task import SACTask
    from .user import User

class Trace(AIEntityMixin, Base):
    __tablename__ = "traces"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("sac_tasks.id"), nullable=True)
    
    name: Mapped[str] = mapped_column(String(100))          # "chat_completion", "sac_react_loop"
    
    input: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    
    trace_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    user: Mapped["User"] = relationship("User")
    session: Mapped[Optional["ChatSession"]] = relationship("ChatSession")
    task: Mapped[Optional["SACTask"]] = relationship("SACTask")
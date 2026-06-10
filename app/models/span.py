from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from decimal import Decimal
from sqlalchemy import DECIMAL, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import AIEntityMixin, Base

if TYPE_CHECKING:
    from .trace import Trace

class Span(AIEntityMixin, Base):
    __tablename__ = "spans"

    trace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("traces.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_span_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("spans.id", ondelete="SET NULL"), nullable=True)

    name: Mapped[str] = mapped_column(String(100))   # "llm_call", "search_web_many", "reasoner_node"
    type: Mapped[str] = mapped_column(String(30))    # "llm", "tool", "chain", "agent"
    
    model: Mapped[Optional[str]] = mapped_column(String(50))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(DECIMAL(10,6), default=0)
    
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="success")  # success | error
    
    input: Mapped[Optional[dict]] = mapped_column(JSONB)
    output: Mapped[Optional[dict]] = mapped_column(JSONB)

    trace: Mapped["Trace"] = relationship("Trace", back_populates="spans")
    parent: Mapped[Optional["Span"]] = relationship("Span", remote_side="Span.id")
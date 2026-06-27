import logging
import os
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

from langfuse.langchain import CallbackHandler
from langfuse import Langfuse

from app.config.settings import settings
from app.core.database import SessionLocal
from app.models.sdk_operation import SDKOperation
from app.guardrails.redactor import redact_sensitive_data, truncate_source_snippets

logger = logging.getLogger(__name__)

def get_langfuse_callback(
    user_id: Optional[uuid.UUID] = None,
    session_id: Optional[uuid.UUID] = None,
    trace_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
    assistant_message_id: Optional[uuid.UUID] = None
) -> Optional[CallbackHandler]:
    """
    Get a configured Langfuse CallbackHandler for LangChain / LangGraph.
    """
    if not settings.LANGFUSE_ENABLED:
        return None

    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.warning("Langfuse is enabled but public_key or secret_key is missing.")
        return None

    try:
        # Initialize CallbackHandler
        handler = CallbackHandler(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            user_id=str(user_id) if user_id else None,
            session_id=str(session_id) if session_id else None,
            trace_id=str(trace_id) if trace_id else None
        )
        
        # Add metadata attributes
        if handler.trace:
            handler.trace.update(
                metadata={
                    "run_id": str(trace_id) if trace_id else None,
                    "thread_id": str(session_id) if session_id else None,
                    "project_id": str(project_id) if project_id else None,
                    "assistant_message_id": str(assistant_message_id) if assistant_message_id else None,
                }
            )
        else:
            logger.warning("Langfuse handler.trace is None, metadata not set")
        
        return handler
    except Exception as e:
        logger.error(f"Failed to initialize Langfuse CallbackHandler: {e}", exc_info=True)
        return None

def flush_sdk_operations_to_langfuse(task_id: uuid.UUID, turn_number: int):
    """
    Query SDKOperation logs for a specific task and turn from the database,
    redact sensitive data, and push them to Langfuse as spans.
    """
    if not settings.LANGFUSE_ENABLED:
        return

    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return

    db = SessionLocal()
    try:
        from sqlalchemy import select
        # Query operations from the database
        stmt = select(SDKOperation).where(
            SDKOperation.task_id == task_id,
            SDKOperation.turn_number == turn_number
        ).order_by(SDKOperation.created_at)
        
        operations = db.execute(stmt).scalars().all()
        if not operations:
            return

        # Initialize Langfuse client
        langfuse_client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST
        )

        for op in operations:
            # Redact input parameters
            redacted_input = redact_sensitive_data(op.input_params)
            
            # Apply source snippet truncation if necessary
            if isinstance(redacted_input, dict):
                for k, v in redacted_input.items():
                    if isinstance(v, str):
                        redacted_input[k] = truncate_source_snippets(v, settings.TRACE_SOURCE_SNIPPET_MAX_CHARS)

            # Create span directly linked to the trace_id (task_id)
            op_created_at = op.created_at or datetime.now(timezone.utc)
            langfuse_client.span(
                trace_id=str(task_id),
                name=f"sdk.{op.operation_type}",
                start_time=op_created_at,
                end_time=op_created_at + timedelta(milliseconds=op.duration_ms or 0),
                input=redacted_input,
                output={"result_count": op.result_count},
                metadata={
                    "turn_number": op.turn_number,
                    "cost_usd": op.cost_usd or 0.0,
                    "duration_ms": op.duration_ms
                }
            )
            
        # Flush to send events immediately
        langfuse_client.flush()
        
    except Exception as e:
        logger.error(f"Failed to flush SDK operations to Langfuse: {e}", exc_info=True)
    finally:
        db.close()

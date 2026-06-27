import uuid
import pytest
from unittest.mock import MagicMock, patch

import app.models
from app.config.settings import settings
from app.core.langfuse_tracing import get_langfuse_callback, flush_sdk_operations_to_langfuse
from app.models.sdk_operation import SDKOperation

@pytest.fixture
def override_settings():
    orig_enabled = settings.LANGFUSE_ENABLED
    orig_pub = settings.LANGFUSE_PUBLIC_KEY
    orig_sec = settings.LANGFUSE_SECRET_KEY
    orig_host = settings.LANGFUSE_HOST
    
    settings.LANGFUSE_ENABLED = True
    settings.LANGFUSE_PUBLIC_KEY = "pk-lf-test"
    settings.LANGFUSE_SECRET_KEY = "sk-lf-test"
    settings.LANGFUSE_HOST = "http://localhost:3000"
    
    yield
    
    settings.LANGFUSE_ENABLED = orig_enabled
    settings.LANGFUSE_PUBLIC_KEY = orig_pub
    settings.LANGFUSE_SECRET_KEY = orig_sec
    settings.LANGFUSE_HOST = orig_host


@patch("app.core.langfuse_tracing.CallbackHandler")
def test_get_langfuse_callback(mock_callback_class, override_settings):
    mock_handler = MagicMock()
    mock_callback_class.return_value = mock_handler
    
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    trace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    
    handler = get_langfuse_callback(
        user_id=user_id,
        session_id=session_id,
        trace_id=trace_id,
        project_id=project_id,
        assistant_message_id=assistant_message_id
    )
    
    assert handler is not None
    mock_callback_class.assert_called_once_with(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://localhost:3000",
        user_id=str(user_id),
        session_id=str(session_id),
        trace_id=str(trace_id)
    )
    
    mock_handler.trace.update.assert_called_once_with(
        metadata={
            "run_id": str(trace_id),
            "thread_id": str(session_id),
            "project_id": str(project_id),
            "assistant_message_id": str(assistant_message_id),
        }
    )


@patch("app.core.langfuse_tracing.Langfuse")
@patch("app.core.langfuse_tracing.SessionLocal")
def test_flush_sdk_operations_to_langfuse(mock_session_local, mock_langfuse_class, override_settings):
    # Mock Database
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db
    
    # Create sample SDKOperation
    task_id = uuid.uuid4()
    op = SDKOperation(
        task_id=task_id,
        turn_number=1,
        operation_type="web_search",
        input_params={"query": "my api key: sk-proj-12345678901234567890"},
        result_count=5,
        duration_ms=120,
        cost_usd=None
    )
    
    mock_db.execute().scalars().all.return_value = [op]
    
    # Mock Langfuse Client
    mock_client = MagicMock()
    mock_langfuse_class.return_value = mock_client
    
    flush_sdk_operations_to_langfuse(task_id, 1)
    
    # Verify Langfuse client was initialized correctly
    mock_langfuse_class.assert_called_once_with(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://localhost:3000"
    )
    
    # Verify span was created and input params were redacted
    mock_client.span.assert_called_once()
    kwargs = mock_client.span.call_args.kwargs
    
    assert kwargs["trace_id"] == str(task_id)
    assert kwargs["name"] == "sdk.web_search"
    assert kwargs["input"] == {"query": "my api key: sk-proj-...[REDACTED]"} # Redacted!
    assert kwargs["output"] == {"result_count": 5}
    assert kwargs["metadata"]["turn_number"] == 1
    
    # Verify flush was called
    mock_client.flush.assert_called_once()
    
    # Verify DB session was closed
    mock_db.close.assert_called_once()

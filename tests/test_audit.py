import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.unit_of_work import UnitOfWork
from app.core.audit import log_audit_event, sanitize_audit_context
from app.core.trace import trace_span_isolated
from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.span import Span
from app.models.trace import Trace
from app.shared.enums import MessageStatus


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(db_session):
    """Create a temporary user in the database to satisfy foreign key constraints."""
    user = User(
        username=f"audit_user_{uuid.uuid4().hex[:8]}",
        email=f"audit_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashedpassword123",
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    yield user
    db_session.delete(user)
    db_session.commit()


def test_sanitize_audit_context():
    # Scenario A: Simple dict with sensitive keys
    payload = {
        "username": "developer",
        "api_key": "sk-proj-supersecretkey12345",
        "password": "my_raw_password",
        "nested": {
            "token": "bearer-token-12345",
            "normal_field": "hello"
        }
    }
    sanitized = sanitize_audit_context(payload)
    
    assert sanitized["username"] == "developer"
    assert sanitized["api_key"] == "sk-pro...[MASKED]"
    assert sanitized["password"] == "my_raw...[MASKED]"
    assert sanitized["nested"]["token"] == "bearer...[MASKED]"
    assert sanitized["nested"]["normal_field"] == "hello"

    # Scenario B: Dict containing lists of dicts (recursive list sanitization)
    list_payload = {
        "items": [
            {"name": "App1", "token": "secret-token-value"},
            {"name": "App2", "normal": "public-value"}
        ]
    }
    sanitized_list = sanitize_audit_context(list_payload)
    assert sanitized_list["items"][0]["name"] == "App1"
    assert sanitized_list["items"][0]["token"] == "secret...[MASKED]"
    assert sanitized_list["items"][1]["normal"] == "public-value"


def test_log_audit_event_persists_on_commit(db_session, test_user):
    action_name = f"test.action_{uuid.uuid4().hex[:8]}"
    
    with UnitOfWork(db_session) as uow:
        log_audit_event(
            uow=uow,
            user_id=test_user.id,
            action=action_name,
            status="success",
            context={"file_name": "important.txt"},
            ip_address="127.0.0.1",
            user_agent="pytest-client"
        )
    
    # Verify persistence after Unit of Work context commits on exit
    stmt = select(AuditLog).where(AuditLog.action == action_name)
    record = db_session.execute(stmt).scalars().first()
    
    assert record is not None
    assert record.user_id == test_user.id
    assert record.status == "success"
    assert record.context == {"file_name": "important.txt"}
    assert record.ip_address == "127.0.0.1"
    assert record.user_agent == "pytest-client"
    
    # Cleanup
    db_session.delete(record)
    db_session.commit()


def test_log_audit_event_rolls_back_on_error(db_session, test_user):
    action_name = f"test.failed_action_{uuid.uuid4().hex[:8]}"
    
    try:
        with UnitOfWork(db_session) as uow:
            log_audit_event(
                uow=uow,
                user_id=test_user.id,
                action=action_name,
                status="success",
                context={"test": "rollback"}
            )
            # Simulate a crash/exception inside business logic
            raise ValueError("Forced error to trigger rollback")
    except ValueError:
        pass
        
    # Verify that the audit log was rolled back and NOT saved to database
    stmt = select(AuditLog).where(AuditLog.action == action_name)
    record = db_session.execute(stmt).scalars().first()
    assert record is None


def test_trace_span_isolated_persists_despite_rollback(db_session, test_user):
    # First, create a mock Trace in DB since Span requires a trace_id foreign key
    trace = Trace(
        user_id=test_user.id,
        name="test_trace",
        trace_metadata={},
        tags=[]
    )
    db_session.add(trace)
    db_session.commit()
    db_session.refresh(trace)
    
    span_name = f"span_{uuid.uuid4().hex[:8]}"
    
    try:
        # Run trace span in isolated context, raising an exception to rollback the outer logic
        with trace_span_isolated(
            trace_id=trace.id,
            span_name=span_name,
            span_type="llm",
            model_name="gpt-4o"
        ) as span_data:
            span_data["input"] = {"prompt": "Hello"}
            span_data["output"] = {"response": "Hi"}
            span_data["prompt_tokens"] = 10
            span_data["completion_tokens"] = 5
            span_data["cost_usd"] = 0.0003
            
            # Simulate a business logic crash
            raise RuntimeError("Outer business transaction crash")
    except RuntimeError:
        pass
        
    # Verify the span record was still committed and persisted to DB
    # (Since it uses an isolated connection, it escapes the outer exception rollback)
    stmt = select(Span).where(Span.name == span_name)
    record = db_session.execute(stmt).scalars().first()
    
    assert record is not None
    assert record.status == "error"  # Status is captured as error due to exception
    assert record.input == {"prompt": "Hello"}
    assert record.output == {"error": "Outer business transaction crash"}
    assert record.prompt_tokens == 10
    assert record.completion_tokens == 5
    assert record.total_tokens == 15  # total_tokens must sum prompt + completion
    assert record.cost_usd == Decimal("0.0003")
    
    # Cleanup
    db_session.delete(record)
    db_session.delete(trace)
    db_session.commit()


def test_audit_prometheus_metrics(db_session, test_user):
    from app.observability.metrics import AUDIT_LOG_EVENTS_TOTAL
    
    action_name = f"test.metric_action_{uuid.uuid4().hex[:8]}"
    
    # Get initial value
    initial_event_val = AUDIT_LOG_EVENTS_TOTAL.labels(action=action_name, status="success")._value.get()
    
    with UnitOfWork(db_session) as uow:
        log_audit_event(
            uow=uow,
            user_id=test_user.id,
            action=action_name,
            status="success",
            context={"metric": "test"}
        )
        
    # Check that event count incremented by 1
    new_event_val = AUDIT_LOG_EVENTS_TOTAL.labels(action=action_name, status="success")._value.get()
    assert new_event_val == initial_event_val + 1
    
    # Cleanup DB record
    stmt = select(AuditLog).where(AuditLog.action == action_name)
    record = db_session.execute(stmt).scalars().first()
    if record:
        db_session.delete(record)
        db_session.commit()


def test_audit_prometheus_failed_metric():
    from unittest.mock import MagicMock
    from app.observability.metrics import AUDIT_LOG_FAILED_TOTAL
    
    action_name = f"test.failed_metric_action_{uuid.uuid4().hex[:8]}"
    initial_failed_val = AUDIT_LOG_FAILED_TOTAL.labels(action=action_name)._value.get()
    
    mock_uow = MagicMock()
    mock_uow.audit_logs.create.side_effect = Exception("Mock DB Failure")
    
    log_audit_event(
        uow=mock_uow,
        user_id=None,
        action=action_name,
        status="success"
    )
    
    new_failed_val = AUDIT_LOG_FAILED_TOTAL.labels(action=action_name)._value.get()
    assert new_failed_val == initial_failed_val + 1


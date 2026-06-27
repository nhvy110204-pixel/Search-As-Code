import uuid
import logging
from typing import Any, Dict, Optional

from app.core.unit_of_work import UnitOfWork
from app.observability.metrics import record_audit_log_event, record_audit_log_failed

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "private_key", "authorization"}


def sanitize_audit_context(context: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = {}
    for k, v in context.items():
        if any(sk in k.lower() for sk in SENSITIVE_KEYS):
            if isinstance(v, str) and len(v) > 8:
                sanitized[k] = f"{v[:6]}...[MASKED]"
            else:
                sanitized[k] = "[MASKED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_audit_context(v)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_audit_context(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            sanitized[k] = v
    return sanitized


def log_audit_event(
    uow: UnitOfWork,
    *,
    user_id: Optional[uuid.UUID] = None,
    project_id: Optional[uuid.UUID] = None,
    action: str,
    status: str,
    context: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> None:
    """
    Log audit event with automatic sanitization of sensitive data.
    
    This function is designed to be safe - errors in audit logging should not
    crash the main business logic flow.
    
    Args:
        uow: UnitOfWork instance with audit_logs repository
        user_id: Optional UUID of the user performing the action
        project_id: Optional UUID of the related project
        action: Action description (e.g., "document.delete", "api_key.create")
        status: Status of the action ("success" or "failed")
        context: Optional additional context data (will be sanitized)
        ip_address: Optional IP address of the request
        user_agent: Optional user agent string
    """
    try:
        clean_context = sanitize_audit_context(context or {})
        uow.audit_logs.create(
            user_id=user_id,
            project_id=project_id,
            action=action,
            status=status,
            context=clean_context,
            ip_address=ip_address,
            user_agent=user_agent
        )
        # Record in Prometheus
        record_audit_log_event(action=action, status=status)
    except Exception as e:
        logger.error(f"Failed to write audit log for action {action}: {e}", exc_info=True)
        # Record failure in Prometheus
        record_audit_log_failed(action=action)

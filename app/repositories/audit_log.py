from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog, object, object]):
    def __init__(self, db: Session):
        super().__init__(AuditLog, db)

    def create(
        self,
        *,
        user_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
        action: str,
        status: str,
        context: dict,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """Create audit log entry directly with kwargs"""
        db_obj = AuditLog(
            user_id=user_id,
            project_id=project_id,
            action=action,
            status=status,
            context=context,
            ip_address=ip_address,
            user_agent=user_agent
        )
        self.db.add(db_obj)
        self.db.flush()
        self.db.refresh(db_obj)
        return db_obj

    def get_by_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
        action: Optional[str] = None
    ):
        """Get audit logs for a specific user"""
        filters = {"user_id": user_id}
        if action:
            filters["action"] = action
        return self.get_multi(skip=skip, limit=limit, filters=filters, order_by=["-created_at"])

    def get_by_project(
        self,
        project_id: UUID,
        skip: int = 0,
        limit: int = 100,
        action: Optional[str] = None
    ):
        """Get audit logs for a specific project"""
        filters = {"project_id": project_id}
        if action:
            filters["action"] = action
        return self.get_multi(skip=skip, limit=limit, filters=filters, order_by=["-created_at"])

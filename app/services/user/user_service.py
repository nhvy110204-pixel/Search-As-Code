import logging
from typing import Optional, Dict, Any
from uuid import UUID

from app.services.core.base import BaseService
from app.repositories.user import UserRepository
from app.models.user import User
from app.core.security import get_password_hash, verify_password
from app.schemas.dto.user import (
    UserCreate,
    UserCreateInternal,
    UserListResponse,
    UserUpdate,
)
from app.services.core.redis_service import redis_cache_service
from app.core.logger import service_boundary
from app.core.audit import log_audit_event

logger = logging.getLogger(__name__)


class UserService(BaseService[User, UserCreate, UserUpdate]):
    """User domain service with authentication and pagination support."""

    def __init__(self, repository: UserRepository, uow=None):
        super().__init__(repository, uow)

    @service_boundary("Create User")
    def create(self, obj_in: UserCreate, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> User:
        """Create user with password hashing (business logic)."""
        hashed = get_password_hash(obj_in.password)
        internal = UserCreateInternal(
            email=obj_in.email,
            username=obj_in.username,
            full_name=obj_in.full_name,
            avatar_url=obj_in.avatar_url,
            hashed_password=hashed,
            is_active=obj_in.is_active,
        )
        user = self.repo.create_user(internal)
        if user and self.uow:
            log_audit_event(
                uow=self.uow,
                user_id=user.id,
                action="user.register",
                status="success",
                context={
                    "user_id": str(user.id),
                    "username": user.username,
                    "email": user.email
                },
                ip_address=ip_address,
                user_agent=user_agent
            )
        return user

    @service_boundary("Authenticate User")
    def authenticate(self, identifier: str, password: str) -> Optional[User]:
        """Authenticate user by email or username."""
        normalized = identifier.strip()
        user = self.repo.get_by_email(normalized.lower()) if "@" in normalized else self.repo.get_by_username(normalized)
        if user and not user.is_deleted and user.is_active and verify_password(password, user.hashed_password):
            return user
        return None

    @service_boundary("Get Users Paginated")
    def get_users_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> UserListResponse:
        """Get paginated users with optional filters."""
        items, total = self.repo.list_users(page=page, page_size=page_size, filters=filters)
        return UserListResponse(items=items, total=total, page=page, page_size=page_size)

    @service_boundary("Update User")
    def update(
        self,
        id: UUID,
        obj_in: UserUpdate | Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Optional[User]:
        """Update user and invalidate their Redis session cache."""
        is_updating_keys = False
        if isinstance(obj_in, dict):
            is_updating_keys = "encrypted_custom_api_keys" in obj_in
        elif hasattr(obj_in, "encrypted_custom_api_keys"):
            is_updating_keys = obj_in.encrypted_custom_api_keys is not None

        user = super().update(id, obj_in)
        if user:
            try:
                r = redis_cache_service.redis
                if r is not None:
                    r.delete(f"user:session:{id}")
            except Exception as e:
                logger.warning("Failed to invalidate user session cache: %s", e)
            if self.uow and is_updating_keys:
                log_audit_event(
                    uow=self.uow,
                    user_id=id,
                    action="user.update_api_keys",
                    status="success",
                    context={
                        "user_id": str(id),
                        "message": "Custom third-party API keys updated"
                    },
                    ip_address=ip_address,
                    user_agent=user_agent
                )
        return user

    @service_boundary("Delete User")
    def delete(
        self,
        id: UUID,
        actor_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        hard: bool = False
    ) -> bool:
        """Delete user and invalidate their Redis session cache."""
        ok = super().delete(id, hard)
        if ok:
            try:
                r = redis_cache_service.redis
                if r is not None:
                    r.delete(f"user:session:{id}")
            except Exception as e:
                logger.warning("Failed to invalidate user session cache: %s", e)
            if self.uow:
                log_audit_event(
                    uow=self.uow,
                    user_id=actor_id or id,
                    action="user.delete",
                    status="success",
                    context={
                        "target_user_id": str(id),
                        "hard_delete": hard
                    },
                    ip_address=ip_address,
                    user_agent=user_agent
                )
        return ok

    @service_boundary("Change Password")
    def change_password(
        self,
        id: UUID,
        old_password: str,
        new_password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """Change user password securely and write audit logs."""
        user = self.get(id)
        if not user or not verify_password(old_password, user.hashed_password):
            if self.uow:
                log_audit_event(
                    uow=self.uow,
                    user_id=id,
                    action="user.password_change",
                    status="failed",
                    context={"reason": "Incorrect old password"},
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            return False

        hashed = get_password_hash(new_password)
        self.repo.update(user, {"hashed_password": hashed})

        if self.uow:      
            log_audit_event(
                uow=self.uow,
                user_id=id,
                action="user.password_change",
                status="success",
                context={},
                ip_address=ip_address,
                user_agent=user_agent
            )
        return True

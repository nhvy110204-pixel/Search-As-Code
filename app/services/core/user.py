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

logger = logging.getLogger(__name__)


class UserService(BaseService[User, UserCreate, UserUpdate]):
    """User domain service with authentication and pagination support."""

    def __init__(self, repository: UserRepository):
        super().__init__(repository)

    @service_boundary("Create User")
    def create(self, obj_in: UserCreate) -> User:
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
        return self.repo.create_user(internal)

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
    def update(self, id: UUID, obj_in: UserUpdate | Dict[str, Any]) -> Optional[User]:
        """Update user and invalidate their Redis session cache."""
        user = super().update(id, obj_in)
        if user:
            try:
                r = redis_cache_service.redis
                if r is not None:
                    r.delete(f"user:session:{id}")
            except Exception as e:
                logger.warning("Failed to invalidate user session cache: %s", e)
        return user

    @service_boundary("Delete User")
    def delete(self, id: UUID, hard: bool = False) -> bool:
        """Delete user and invalidate their Redis session cache."""
        ok = super().delete(id, hard)
        if ok:
            try:
                r = redis_cache_service.redis
                if r is not None:
                    r.delete(f"user:session:{id}")
            except Exception as e:
                logger.warning("Failed to invalidate user session cache: %s", e)
        return ok

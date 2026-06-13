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


class UserService(BaseService[User, UserCreate, UserUpdate]):
    """User domain service with authentication and pagination support."""

    def __init__(self, repository: UserRepository):
        super().__init__(repository)

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

    def authenticate(self, email: str, password: str) -> Optional[User]:
        """Authenticate user by email and password."""
        user = self.repo.get_by(email=email)
        if user and verify_password(password, user.hashed_password):
            return user
        return None

    def get_users_paginated(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> UserListResponse:
        """Get paginated users with optional filters."""
        items, total = self.repo.list_users(page=page, page_size=page_size, filters=filters)
        return UserListResponse(items=items, total=total, page=page, page_size=page_size)

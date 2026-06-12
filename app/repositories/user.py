from typing import Optional
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.base import BaseRepository
from app.schemas.dto.user import UserListResponse


class UserRepository(BaseRepository[User, object, object]):
    def __init__(self, db: Session):
        super().__init__(User, db)

    def get_by_email(self, email: str) -> Optional[User]:
        return self.get_by(email=email)

    def get_by_username(self, username: str) -> Optional[User]:
        return self.get_by(username=username)

    def create_user(self, internal_model) -> User:
        return super().create(internal_model)
    
    def get_user(self, id, include_deleted: bool = False, options: list | None = None) -> Optional[User]:
        return self.get(id=id, include_deleted=include_deleted, options=options)

    def list_users(
        self,
        page: int = 1,
        page_size: int = 100,
        filters: dict | None = None,
        order_by: list | None = None,
        options: list | None = None,
        include_deleted: bool = False,
    ):
        """Return raw data for pagination: (items, total).

        Repository should remain DB-focused and not construct response DTOs or
        know about `page`/`page_size` semantics beyond calculating offsets.
        """
        if page < 1:
            page = 1
        skip = (page - 1) * page_size
        items = self.get_multi(skip=skip, limit=page_size, filters=filters, order_by=order_by, options=options, include_deleted=include_deleted)
        total = self.count(filters=filters, include_deleted=include_deleted)
        return items, total
    
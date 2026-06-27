from typing import Optional
from uuid import UUID
from sqlalchemy.orm import Session

from app.models.api_key import APIKey
from app.repositories.base import BaseRepository


class APIKeyRepository(BaseRepository[APIKey, object, object]):
    def __init__(self, db: Session):
        super().__init__(APIKey, db)

    def get_by_hash(self, key_hash: str) -> Optional[APIKey]:
        """Retrieve API Key by its SHA-256 hash."""
        return self.get_by(key_hash=key_hash)

    def list_by_user(self, user_id: UUID, skip: int = 0, limit: int = 100):
        """Retrieve active API keys for a specific user."""
        return self.get_multi(
            skip=skip,
            limit=limit,
            filters={"user_id": user_id},
            order_by=["-created_at"]
        )

from typing import Optional
from sqlalchemy.orm import Session

from app.models.user_preference import UserPreference
from app.repositories.base import BaseRepository


class UserPreferenceRepository(BaseRepository[UserPreference, object, object]):
    def __init__(self, db: Session):
        super().__init__(UserPreference, db)

    def get_by_user_id(self, user_id: str) -> Optional[UserPreference]:
        return self.get_by(user_id=user_id)

    def get_or_create_by_user_id(self, user_id: str) -> UserPreference:
        pref = self.get_by_user_id(user_id)
        if not pref:
            pref = self.create({"user_id": user_id, "preferences": {}})
        return pref

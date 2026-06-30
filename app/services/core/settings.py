from typing import Optional
from uuid import UUID

from app.models.user_preference import UserPreference
from app.repositories.user_preference import UserPreferenceRepository
from app.schemas.dto.settings import SettingsResponse, SettingsUpdate
from app.services.core.base import BaseService
from app.config.settings import settings


class SettingsService(BaseService[UserPreference, dict, SettingsUpdate]):
    def __init__(self, repository: UserPreferenceRepository):
        super().__init__(repository)

    def get_user_settings(self, user_id: str) -> SettingsResponse:
        """Get settings for a user, return default if not exists"""
        pref = self.repo.get_or_create_by_user_id(user_id)
        preferences = pref.preferences.copy()
        
        # Populate provider availability based on environment variables
        providers = preferences.get("providers") or {}
        
        # OpenAI
        openai_pref = providers.get("openai") or {}
        if not openai_pref.get("has_api_key"):
            openai_pref["has_api_key"] = bool(settings.OPENAI_API_KEY)
            openai_pref["configured"] = openai_pref.get("configured", False)
        providers["openai"] = openai_pref
        
        preferences["providers"] = providers
        return SettingsResponse.model_validate(preferences)

    def update_user_settings(self, user_id: str, settings_update: SettingsUpdate) -> SettingsResponse:
        """Update settings for a user"""
        pref = self.repo.get_or_create_by_user_id(user_id)
        current_preferences = pref.preferences.copy()
        
        # Merge update data
        update_data = settings_update.model_dump(exclude_unset=True)
        current_preferences.update(update_data)
        
        # Update the preference
        self.repo.update(pref, {"preferences": current_preferences})
        
        return SettingsResponse.model_validate(current_preferences)

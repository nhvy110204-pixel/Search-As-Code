from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.core.unit_of_work import UnitOfWork
from app.models.user import User
from app.services.core.settings import SettingsService
from app.schemas.dto.settings import SettingsResponse, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def get_settings_service(db: Session = Depends(get_db)):
    """Dependency that yields a SettingsService within a UnitOfWork."""
    with UnitOfWork(db) as uow:
        yield SettingsService(repository=uow.user_preferences)


def get_settings_service_write(db: Session = Depends(get_db)):
    """Dependency that yields a SettingsService within a write UnitOfWork."""
    with UnitOfWork(db) as uow:
        yield SettingsService(repository=uow.user_preferences)


@router.get("", response_model=SettingsResponse)
def get_settings(
    current_user: User = Depends(get_current_user),
    service: SettingsService = Depends(get_settings_service)
):
    """Get user-specific settings"""
    return service.get_user_settings(str(current_user.id))


@router.put("", response_model=SettingsResponse)
def update_settings(
    settings_update: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    service: SettingsService = Depends(get_settings_service_write)
):
    """Update user-specific settings"""
    return service.update_user_settings(str(current_user.id), settings_update)

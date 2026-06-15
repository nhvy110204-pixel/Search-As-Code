from uuid import UUID
from fastapi import HTTPException
from app.core.unit_of_work import UnitOfWork


def check_user_quota(
    uow_factory: UnitOfWork,
    user_id: UUID,
    project_id: UUID,
    file_size: int
) -> None:
    with uow_factory() as uow:
        quota_ok, current_usage, quota_limit = uow.documents.check_user_quota(user_id, project_id)
        
        if not quota_ok:
            quota_limit_gb = quota_limit / (1024 * 1024 * 1024)
            current_usage_gb = current_usage / (1024 * 1024 * 1024)
            raise HTTPException(
                status_code=429,
                detail=f"Storage quota exceeded. Current usage: {current_usage_gb:.2f}GB, Limit: {quota_limit_gb:.2f}GB"
            )

        if current_usage + file_size > quota_limit:
            quota_limit_gb = quota_limit / (1024 * 1024 * 1024)
            new_usage_gb = (current_usage + file_size) / (1024 * 1024 * 1024)
            raise HTTPException(
                status_code=429,
                detail=f"File would exceed storage quota. New usage would be: {new_usage_gb:.2f}GB, Limit: {quota_limit_gb:.2f}GB"
            )

import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.shared.enums import ProjectStatus

class ProjectBase(BaseModel):
    name: str = Field(..., max_length=255, description="Tên của knowledge workspace")
    description: Optional[str] = Field(None, description="Mô tả chi tiết workspace")
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE)
    settings: dict[str, Any] = Field(default_factory=dict, description="Cấu hình mở rộng dạng JSONB")

class ProjectCreate(ProjectBase):
    owner_user_id: uuid.UUID = Field(..., description="ID của user sở hữu project")

class ProjectCreateRequest(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    settings: Optional[dict[str, Any]] = None

class ProjectResponse(ProjectBase):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ProjectListResponse(BaseModel):
    items: List[ProjectResponse]
    total: int
    page: int
    page_size: int

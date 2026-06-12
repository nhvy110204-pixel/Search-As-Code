from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
)
from uuid import UUID


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$"  
    )
    full_name: str | None = Field(None, max_length=100)
    avatar_url: str | None = Field(None, max_length=500)
    password: str = Field(
        min_length=8,
        max_length=128,
    )
    is_active: bool = True


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(None, min_length=3, max_length=50)
    full_name: str | None = Field(None, max_length=100)
    avatar_url: str | None = Field(None, max_length=500)
    is_active: bool | None = None
    metadata_: dict[str, Any] | None = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(
        min_length=8,
        max_length=128,
    )


class UserCreateInternal(BaseModel):
    email: EmailStr
    username: str
    full_name: str | None = None
    avatar_url: str | None = None
    hashed_password: str
    is_active: bool = True


class UserUpdateInternal(UserUpdate):
    hashed_password: str | None = None


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    username: str
    full_name: str | None
    avatar_url: str | None
    is_active: bool
    metadata_: dict[str, Any]
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(
        from_attributes=True
    )


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int
    model_config = ConfigDict(
        from_attributes=True
    )
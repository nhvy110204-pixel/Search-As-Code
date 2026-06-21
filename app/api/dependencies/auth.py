from __future__ import annotations

import json
import uuid
import logging
import hashlib
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user import UserRepository
from app.services.core.redis_service import redis_cache_service

bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(credentials.credentials)

    # 1. Try to fetch user from Redis Cache
    cache_key = f"user:session:{user_id}"
    try:
        r = redis_cache_service.redis
        if r is not None:
            cached_data = r.get(cache_key)
            if cached_data:
                user_data = json.loads(cached_data)

                # Verify checksum to ensure data integrity
                expected_checksum = hashlib.sha256(
                    f"{user_data['id']}:{user_data['username']}:{user_data['email']}:{user_data['is_active']}:{user_data['is_deleted']}:{user_data['has_custom_keys']}".encode("utf-8")
                ).hexdigest()

                if user_data.get("checksum") == expected_checksum:
                    # Construct transient User model (never caches actual custom API keys)
                    user = User(
                        id=uuid.UUID(user_data["id"]),
                        username=user_data["username"],
                        email=user_data["email"],
                        is_active=user_data["is_active"],
                        is_deleted=user_data["is_deleted"],
                        encrypted_custom_api_keys=None
                    )

                    if user.is_deleted or not user.is_active:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or inactive user",
                            headers={"WWW-Authenticate": "Bearer"},
                        )
                    return user
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Redis user session cache error: %s. Falling back to DB.", e)

    # 2. Cache Miss: Query PostgreSQL
    user = UserRepository(db).get_user(user_id)
    if not user or user.is_deleted or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Populate Redis Cache (Flag + Checksum)
    try:
        r = redis_cache_service.redis
        if r is not None:
            has_custom_keys = user.encrypted_custom_api_keys is not None

            state_checksum = hashlib.sha256(
                f"{str(user.id)}:{user.username}:{user.email}:{user.is_active}:{user.is_deleted}:{has_custom_keys}".encode("utf-8")
            ).hexdigest()

            user_data = {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "is_active": user.is_active,
                "is_deleted": user.is_deleted,
                "has_custom_keys": has_custom_keys,
                "checksum": state_checksum
            }

            r.setex(cache_key, 300, json.dumps(user_data))
    except Exception as e:
        logger.warning("Failed to cache user session in Redis: %s", e)

    return user

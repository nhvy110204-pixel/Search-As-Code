from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
import hashlib
from jose import JWTError, jwt
from uuid import UUID
import uuid

from app.config.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    return pwd_context.needs_update(hashed_password)


def create_access_token(user_id: UUID) -> str:
    return _create_token(
        user_id=user_id,
        secret_key=settings.JWT_SECRET_KEY,
        expires_delta=timedelta(weeks=settings.JWT_ACCESS_TOKEN_EXPIRE_WEEKS),
        token_type="access",
    )


def create_refresh_token(user_id: UUID, token_id: str | None = None) -> str:
    return _create_token(
        user_id=user_id,
        secret_key=settings.JWT_REFRESH_SECRET_KEY,
        expires_delta=timedelta(weeks=settings.JWT_REFRESH_TOKEN_EXPIRE_WEEKS),
        token_type="refresh",
        token_id=token_id,
    )


def decode_refresh_token(token: str) -> UUID:
    return decode_refresh_token_payload(token)["user_id"]


def decode_refresh_token_payload(token: str) -> dict:
    return _decode_token(
        token=token,
        secret_key=settings.JWT_REFRESH_SECRET_KEY,
        expected_type="refresh",
        invalid_detail="Invalid refresh token",
    )


def decode_access_token(token: str) -> UUID:
    return _decode_token(
        token=token,
        secret_key=settings.JWT_SECRET_KEY,
        expected_type="access",
        invalid_detail="Invalid access token",
    )["user_id"]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_token(user_id: UUID, secret_key: str, expires_delta: timedelta, token_type: str, token_id: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "jti": token_id or str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, secret_key, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str, secret_key: str, expected_type: str, invalid_detail: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=invalid_detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=invalid_detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = payload.get("sub") or payload.get("user_id")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=invalid_detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(str(subject))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=invalid_detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "user_id": user_id,
        "jti": payload.get("jti"),
        "exp": payload.get("exp"),
        "type": expected_type,
    }

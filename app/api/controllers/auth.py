from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token_payload,
    hash_token,
)
from app.core.unit_of_work import UnitOfWork
from app.models.auth_refresh_token import AuthRefreshToken
from app.schemas.dto.user import TokenRefreshRequest, TokenResponse, UserLogin
from app.services.core.user import UserService

router = APIRouter(prefix="/auth", tags=["Auth"])


def _token_expiry_seconds(weeks: int) -> int:
    return weeks * 7 * 24 * 60 * 60


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


def _create_persisted_refresh_token(db: Session, user_id, request: Request) -> str:
    token_id = str(uuid.uuid4())
    refresh_token = create_refresh_token(user_id, token_id=token_id)
    expires_at = datetime.now(timezone.utc) + timedelta(weeks=settings.JWT_REFRESH_TOKEN_EXPIRE_WEEKS)
    db_token = AuthRefreshToken(
        user_id=user_id,
        token_hash=hash_token(refresh_token),
        jti=token_id,
        expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    db.add(db_token)
    db.flush()
    db.refresh(db_token)
    return refresh_token


def _build_token_response(db: Session, user, request: Request) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=_create_persisted_refresh_token(db, user.id, request),
        expires_in_seconds=_token_expiry_seconds(settings.JWT_ACCESS_TOKEN_EXPIRE_WEEKS),
        refresh_expires_in_seconds=_token_expiry_seconds(settings.JWT_REFRESH_TOKEN_EXPIRE_WEEKS),
        user=user,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, request: Request, db: Session = Depends(get_db)):
    with UnitOfWork(db) as uow:
        user = UserService(repository=uow.users, uow=uow).authenticate(payload.identifier, payload.password)
        if not user:
            from app.core.audit import log_audit_event
            client_ip = _client_ip(request)
            user_agent = request.headers.get("user-agent")
            log_audit_event(
                uow=uow,
                user_id=None,
                action="auth.login_failed",
                status="failed",
                context={"identifier": payload.identifier},
                ip_address=client_ip,
                user_agent=user_agent
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return _build_token_response(db, user, request)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: TokenRefreshRequest, request: Request, db: Session = Depends(get_db)):
    decoded = decode_refresh_token_payload(payload.refresh_token)
    token_hash = hash_token(payload.refresh_token)
    now = datetime.now(timezone.utc)

    with UnitOfWork(db) as uow:
        stmt = select(AuthRefreshToken).where(
            AuthRefreshToken.token_hash == token_hash,
            AuthRefreshToken.jti == decoded["jti"],
            AuthRefreshToken.user_id == decoded["user_id"],
            AuthRefreshToken.is_deleted == False,
        )
        existing_token = db.execute(stmt).scalars().first()
        if not existing_token or existing_token.revoked_at or existing_token.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = uow.users.get_user(decoded["user_id"])
        if not user or user.is_deleted or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        response = _build_token_response(db, user, request)
        replacement = db.execute(
            select(AuthRefreshToken).where(AuthRefreshToken.token_hash == hash_token(response.refresh_token))
        ).scalars().first()
        existing_token.revoked_at = now
        existing_token.replaced_by_token_id = replacement.id if replacement else None
        db.add(existing_token)
        return response

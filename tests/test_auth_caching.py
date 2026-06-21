import json
import uuid
import pytest
import hashlib
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from app.api.dependencies.auth import get_current_user
from app.models.user import User
from app.services.core.user import UserService
from app.schemas.dto.user import UserUpdate

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def mock_repo():
    return MagicMock()

@patch("app.api.dependencies.auth.redis_cache_service")
@patch("app.api.dependencies.auth.UserRepository")
@patch("app.api.dependencies.auth.decode_access_token")
def test_cache_miss_populates_redis(
    mock_decode, mock_user_repo_class, mock_redis_service, mock_db
):
    user_id = uuid.uuid4()
    mock_decode.return_value = user_id
    
    # Mock DB user
    mock_user = User(
        id=user_id,
        username="test_caching_user",
        email="cache@example.com",
        is_active=True,
        is_deleted=False,
        encrypted_custom_api_keys="sk-proj-some-encrypted-stuff"
    )
    
    mock_repo_inst = MagicMock()
    mock_repo_inst.get_user.return_value = mock_user
    mock_user_repo_class.return_value = mock_repo_inst
    
    # Mock Redis (Cache Miss)
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    mock_redis_service.redis = mock_redis
    
    # Exec
    mock_credentials = MagicMock()
    mock_credentials.credentials = "test-token"
    mock_credentials.scheme = "Bearer"
    
    user = get_current_user(credentials=mock_credentials, db=mock_db)
    
    # Assertions
    assert user == mock_user
    mock_repo_inst.get_user.assert_called_once_with(user_id)
    
    # Verify it saved to Redis
    mock_redis.get.assert_called_once_with(f"user:session:{user_id}")
    mock_redis.setex.assert_called_once()
    
    # Inspect arguments passed to setex
    args, kwargs = mock_redis.setex.call_args
    assert args[0] == f"user:session:{user_id}"
    assert args[1] == 300  # 5 minutes TTL
    
    saved_data = json.loads(args[2])
    assert saved_data["id"] == str(user_id)
    assert saved_data["username"] == "test_caching_user"
    assert saved_data["email"] == "cache@example.com"
    assert saved_data["is_active"] is True
    assert saved_data["is_deleted"] is False
    assert saved_data["has_custom_keys"] is True
    # Verify sensitive actual key payload was NOT saved to Redis
    assert "encrypted_custom_api_keys" not in saved_data
    assert "checksum" in saved_data

@patch("app.api.dependencies.auth.redis_cache_service")
@patch("app.api.dependencies.auth.UserRepository")
@patch("app.api.dependencies.auth.decode_access_token")
def test_cache_hit_bypasses_db_query(
    mock_decode, mock_user_repo_class, mock_redis_service, mock_db
):
    user_id = uuid.uuid4()
    mock_decode.return_value = user_id
    
    # Prep cached payload
    has_custom_keys = False
    state_checksum = hashlib.sha256(
        f"{str(user_id)}:test_cached:cached@example.com:True:False:{has_custom_keys}".encode("utf-8")
    ).hexdigest()
    
    cached_payload = {
        "id": str(user_id),
        "username": "test_cached",
        "email": "cached@example.com",
        "is_active": True,
        "is_deleted": False,
        "has_custom_keys": has_custom_keys,
        "checksum": state_checksum
    }
    
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached_payload)
    mock_redis_service.redis = mock_redis
    
    mock_repo_inst = MagicMock()
    mock_user_repo_class.return_value = mock_repo_inst
    
    mock_credentials = MagicMock()
    mock_credentials.credentials = "test-token"
    mock_credentials.scheme = "Bearer"
    
    # Exec
    user = get_current_user(credentials=mock_credentials, db=mock_db)
    
    # Assert transient User constructed correctly
    assert user.id == user_id
    assert user.username == "test_cached"
    assert user.email == "cached@example.com"
    assert user.is_active is True
    assert user.is_deleted is False
    assert user.encrypted_custom_api_keys is None
    
    # DB get_user must NEVER be called
    mock_repo_inst.get_user.assert_not_called()

@patch("app.api.dependencies.auth.redis_cache_service")
@patch("app.api.dependencies.auth.UserRepository")
@patch("app.api.dependencies.auth.decode_access_token")
def test_invalid_checksum_falls_back_to_db(
    mock_decode, mock_user_repo_class, mock_redis_service, mock_db
):
    user_id = uuid.uuid4()
    mock_decode.return_value = user_id
    
    cached_payload = {
        "id": str(user_id),
        "username": "test_cached",
        "email": "cached@example.com",
        "is_active": True,
        "is_deleted": False,
        "has_custom_keys": False,
        "checksum": "wrong-tampered-checksum"
    }
    
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(cached_payload)
    mock_redis_service.redis = mock_redis
    
    # Setup DB fallback response
    mock_user = User(
        id=user_id,
        username="test_caching_user",
        email="cache@example.com",
        is_active=True,
        is_deleted=False
    )
    mock_repo_inst = MagicMock()
    mock_repo_inst.get_user.return_value = mock_user
    mock_user_repo_class.return_value = mock_repo_inst
    
    mock_credentials = MagicMock()
    mock_credentials.credentials = "test-token"
    mock_credentials.scheme = "Bearer"
    
    # Exec
    user = get_current_user(credentials=mock_credentials, db=mock_db)
    
    # Assert fallback to DB occurred
    assert user == mock_user
    mock_repo_inst.get_user.assert_called_once_with(user_id)

@patch("app.services.core.user.redis_cache_service")
@patch("app.services.core.user.BaseService")
def test_user_update_invalidates_cache(mock_base_service, mock_redis_service):
    user_id = uuid.uuid4()
    mock_redis = MagicMock()
    mock_redis_service.redis = mock_redis
    
    # Mock BaseService.update to return a User instance
    mock_user = User(id=user_id)
    mock_base_service.update = MagicMock(return_value=mock_user)
    
    # Create service
    mock_repo = MagicMock()
    service = UserService(repository=mock_repo)
    
    # Exec
    service.update(user_id, UserUpdate())
    
    # Verify cache key was deleted
    mock_redis.delete.assert_called_once_with(f"user:session:{user_id}")

@patch("app.services.core.user.redis_cache_service")
@patch("app.services.core.user.BaseService")
def test_user_delete_invalidates_cache(mock_base_service, mock_redis_service):
    user_id = uuid.uuid4()
    mock_redis = MagicMock()
    mock_redis_service.redis = mock_redis
    
    mock_base_service.delete = MagicMock(return_value=True)
    
    mock_repo = MagicMock()
    service = UserService(repository=mock_repo)
    
    # Exec
    service.delete(user_id)
    
    # Verify cache key was deleted
    mock_redis.delete.assert_called_once_with(f"user:session:{user_id}")

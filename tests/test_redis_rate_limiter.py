import pytest
import uuid
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from app.config.settings import settings
from app.services.chat.validators import ChatStreamValidator
from app.shared.enums import ChatStreamStatus

@pytest.fixture
def mock_repo():
    return MagicMock()

@pytest.fixture
def validator(mock_repo):
    return ChatStreamValidator(stream_run_repo=mock_repo)

@patch("app.services.chat.validators.redis_cache_service")
def test_concurrent_rate_limiting_triggered(mock_redis_service, validator):
    # Mock Redis client methods
    mock_redis = MagicMock()
    mock_redis_service.redis = mock_redis
    
    user_id = uuid.uuid4()
    
    # Simulating 3 active concurrent streams (equal to default limit)
    mock_redis.zcard.side_effect = [
        3, # Count for concurrent check
        0, # Count for minute check
        0  # Count for daily check
    ]
    
    with pytest.raises(HTTPException) as exc_info:
        validator.enforce_rate_limits(user_id)
        
    assert exc_info.value.status_code == 429
    assert "Too many active chat streams" in exc_info.value.detail
    mock_redis.zremrangebyscore.assert_called()

@patch("app.services.chat.validators.redis_cache_service")
def test_minute_rate_limiting_triggered(mock_redis_service, validator):
    mock_redis = MagicMock()
    mock_redis_service.redis = mock_redis
    
    user_id = uuid.uuid4()
    
    # Simulating 0 active concurrent streams, but 20 requests in the last minute (equal to default limit)
    mock_redis.zcard.side_effect = [
        0,  # Count for concurrent check
        20, # Count for minute check
        0   # Count for daily check
    ]
    
    with pytest.raises(HTTPException) as exc_info:
        validator.enforce_rate_limits(user_id)
        
    assert exc_info.value.status_code == 429
    assert "Chat stream rate limit exceeded" in exc_info.value.detail

@patch("app.services.chat.validators.redis_cache_service")
def test_daily_rate_limiting_triggered(mock_redis_service, validator):
    mock_redis = MagicMock()
    mock_redis_service.redis = mock_redis
    
    user_id = uuid.uuid4()
    
    # Simulating 0 concurrent, 0 per minute, but 500 requests today (equal to daily limit)
    mock_redis.zcard.side_effect = [
        0,   # Count for concurrent check
        0,   # Count for minute check
        500  # Count for daily check
    ]
    
    with pytest.raises(HTTPException) as exc_info:
        validator.enforce_rate_limits(user_id)
        
    assert exc_info.value.status_code == 429
    assert "Daily chat stream quota exceeded" in exc_info.value.detail

@patch("app.services.chat.validators.redis_cache_service")
def test_rate_limiting_passes_under_limits(mock_redis_service, validator):
    mock_redis = MagicMock()
    mock_redis_service.redis = mock_redis
    
    user_id = uuid.uuid4()
    
    # Simulating all counts under limit
    mock_redis.zcard.side_effect = [
        1,   # 1 active stream (limit 3)
        5,   # 5 requests in last minute (limit 20)
        50   # 50 requests today (limit 500)
    ]
    
    # Should complete without raising any exception
    validator.enforce_rate_limits(user_id)
    assert mock_redis.zcard.call_count == 3

@patch("app.services.chat.validators.redis_cache_service")
def test_redis_error_falls_back_to_db(mock_redis_service, mock_repo, validator):
    # Make Redis operations raise an exception
    mock_redis = MagicMock()
    mock_redis.zremrangebyscore.side_effect = Exception("Redis connection timed out")
    mock_redis_service.redis = mock_redis
    
    user_id = uuid.uuid4()
    
    # Setup DB mock values for fallback (under limits)
    mock_repo.count_user_runs.side_effect = [
        0, # active concurrent runs
        0, # runs in last minute
        0  # runs in last day
    ]
    
    # Should proceed and check DB instead of crashing
    validator.enforce_rate_limits(user_id)
    
    assert mock_repo.count_user_runs.call_count == 3

from uuid import UUID
from datetime import datetime, timedelta
from typing import Tuple, Optional
import redis
import logging
from app.config.settings import settings


class RedisRateLimiter:
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        if redis_client is None:
            redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
        self.redis = redis_client
    
    def check_rate_limit(
        self,
        user_id: UUID,
        project_id: UUID,
        user_limit: int = None,
        project_limit: int = None
    ) -> Tuple[bool, str]:
        if user_limit is None:
            user_limit = settings.RATE_LIMIT_USER_UPLOADS_PER_MINUTE
        if project_limit is None:
            project_limit = settings.RATE_LIMIT_PROJECT_UPLOADS_PER_MINUTE
        
        now = datetime.utcnow()
        one_minute_ago = now - timedelta(minutes=1)
        timestamp = now.timestamp()

        user_key = f"rate_limit:user:{user_id}"
        project_key = f"rate_limit:project:{project_id}"
        
        try:
            self.redis.zremrangebyscore(user_key, 0, one_minute_ago.timestamp())
            self.redis.zremrangebyscore(project_key, 0, one_minute_ago.timestamp())
            
            user_count = self.redis.zcard(user_key)
            if user_count >= user_limit:
                return False, f"User rate limit exceeded: {user_limit} uploads per minute"
            
            project_count = self.redis.zcard(project_key)
            if project_count >= project_limit:
                return False, f"Project rate limit exceeded: {project_limit} uploads per minute"
            
            pipe = self.redis.pipeline()
            pipe.zadd(user_key, {str(timestamp): timestamp})
            pipe.zadd(project_key, {str(timestamp): timestamp})
            pipe.expire(user_key, 60)
            pipe.expire(project_key, 60)
            pipe.execute()
            
            return True, ""
            
        except redis.RedisError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Redis rate limiter error: {e}. Allowing request as fallback.")
            return True, ""
    
    def reset_user(self, user_id: UUID) -> None:
        try:
            user_key = f"rate_limit:user:{user_id}"
            self.redis.delete(user_key)
        except redis.RedisError as e:
            logging.getLogger(__name__).error(f"Failed to reset user rate limit: {e}")
    
    def reset_project(self, project_id: UUID) -> None:
        try:
            project_key = f"rate_limit:project:{project_id}"
            self.redis.delete(project_key)
        except redis.RedisError as e:
            logging.getLogger(__name__).error(f"Failed to reset project rate limit: {e}")
    
    def get_user_usage(self, user_id: UUID) -> int:
        try:
            user_key = f"rate_limit:user:{user_id}"
            one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
            self.redis.zremrangebyscore(user_key, 0, one_minute_ago.timestamp())
            return self.redis.zcard(user_key)
        except redis.RedisError:
            return 0
    
    def get_project_usage(self, project_id: UUID) -> int:
        try:
            project_key = f"rate_limit:project:{project_id}"
            one_minute_ago = datetime.utcnow() - timedelta(minutes=1)
            self.redis.zremrangebyscore(project_key, 0, one_minute_ago.timestamp())
            return self.redis.zcard(project_key)
        except redis.RedisError:
            return 0

rate_limiter = RedisRateLimiter()

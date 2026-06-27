from functools import lru_cache
import os
from pathlib import Path
from typing import Optional

from pydantic import ConfigDict
from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parents[2]
APP_ENV = os.getenv("APP_ENV", "dev").lower()


class Settings(BaseSettings):
    APP_ENV: str = "dev"
    APP_DEBUG: bool = False

    # Database
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str

    # Security & CORS
    FRONTEND_URL: str
    DOMAIN_URL: str
    ALLOWED_ORIGIN_REGEX: str

    # JWT Authentication
    JWT_SECRET_KEY: str
    JWT_REFRESH_SECRET_KEY: str
    JWT_ALGORITHM: str
    JWT_ACCESS_TOKEN_EXPIRE_WEEKS: int
    JWT_REFRESH_TOKEN_EXPIRE_WEEKS: int

    # --- OBSERVABILITY 
    METRICS_ENABLED: bool = True
    METRICS_PATH: str = "/metrics"

    TRACING_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None
    OTEL_SERVICE_NAME: str = "ragflash-backend"
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_HOST: str = "http://localhost:3000"
    TRACE_SOURCE_SNIPPET_MAX_CHARS: int = 1000

    TRACING_BATCH_MAX_QUEUE_SIZE: int = 2048
    TRACING_BATCH_SCHEDULE_DELAY_MS: int = 5000
    TRACING_BATCH_MAX_EXPORT_BATCH_SIZE: int = 512

    TRACING_HEAVY_SANITIZE: bool = False

    # Prometheus multiprocess mode 
    PROMETHEUS_MULTIPROC_DIR: Optional[str] = None

    # Celery configuration
    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_INGESTION_QUEUE: str = "ingestion"

    # Redis configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # File upload configuration
    MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100MB
    USER_QUOTA_DEFAULT_BYTES: int = 100 * 1024 * 1024 * 1024  # 100GB
    ALLOWED_FILE_TYPES: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown"
    ]
    ALLOWED_FILE_EXTENSIONS: list[str] = [".pdf", ".docx", ".txt", ".md"]

    # Rate limiting
    RATE_LIMIT_USER_UPLOADS_PER_MINUTE: int = 10
    RATE_LIMIT_PROJECT_UPLOADS_PER_MINUTE: int = 100

    # Pipeline configuration
    CLEANUP_PIPELINE_STATE_ON_COMPLETION: bool = False  # Keep for debugging by default

    # Embedding provider configuration
    EMBEDDING_PROVIDER: str = "openai"
    EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536
    OPENAI_API_KEY: Optional[str] = None

    # Chat streaming
    CHAT_MODEL_NAME: str = "gpt-4o-mini"
    CHAT_MAX_INPUT_CHARS: int = 12000
    CHAT_HISTORY_LIMIT: int = 30
    CHAT_HISTORY_MAX_CHARS: int = 50000
    CHAT_STREAM_PING_SECONDS: int = 15
    CHAT_STREAM_SEND_TIMEOUT_SECONDS: int = 15
    CHAT_PROVIDER_CHUNK_TIMEOUT_SECONDS: int = 20
    CHAT_STREAM_TOTAL_TIMEOUT_SECONDS: int = 120
    CHAT_STREAM_RATE_LIMIT_PER_MINUTE: int = 20
    CHAT_STREAM_CONCURRENT_LIMIT: int = 3
    CHAT_STREAM_DAILY_LIMIT: int = 500

    # Qdrant Vector DB
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_COLLECTION_CHUNKS: str = "document_chunks"
    QDRANT_COLLECTION_MEMORIES: str = "user_memories"
    
    # Cấu hình Semantic Cache (Qdrant + Redis)
    QDRANT_COLLECTION_SEMANTIC_CACHE: str = "semantic_cache"
    SEMANTIC_CACHE_THRESHOLD: float = 0.92
    SEMANTIC_CACHE_TTL: int = 604800  # Thời gian lưu cache (7 ngày)

    # Sandbox configurations
    SANDBOX_RUNTIME: str = "local"           # "local" or "docker"
    SANDBOX_DOCKER_IMAGE: str = "sac-sandbox:latest"
    SANDBOX_DOCKER_RUNTIME: Optional[str] = None  # "runsc" for gVisor
    SANDBOX_DOCKER_NETWORK: str = "host"     # "host" in dev, custom bridge in prod
    SANDBOX_MEMORY: str = "256m"
    SANDBOX_CPU: float = 0.5
    SANDBOX_USER: str = "sandbox"
    SANDBOX_DOCKER_TIMEOUT: int = 60

    # LiteLLM Proxy and Encryption
    LITELLM_PROXY_URL: Optional[str] = None
    LITELLM_PROXY_KEY: Optional[str] = None
    ENCRYPTION_KEY: Optional[str] = None

    @property
    def DATABASE_URL(self) -> str:
        return URL.create(
            "postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)

    model_config = ConfigDict(
        env_file=str(BASE_DIR / (".env.test" if APP_ENV == "test" else ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

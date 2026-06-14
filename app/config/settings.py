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
    LANGFUSE_API_KEY: Optional[str] = None

    TRACING_BATCH_MAX_QUEUE_SIZE: int = 2048
    TRACING_BATCH_SCHEDULE_DELAY_MS: int = 5000
    TRACING_BATCH_MAX_EXPORT_BATCH_SIZE: int = 512

    TRACING_HEAVY_SANITIZE: bool = False

    # Prometheus multiprocess mode 
    PROMETHEUS_MULTIPROC_DIR: Optional[str] = None

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

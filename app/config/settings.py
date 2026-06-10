from functools import lru_cache
import os
from pathlib import Path
from typing import Optional

from pydantic import computed_field
from sqlalchemy.engine import URL
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]
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

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return str(
            URL.create(
                "postgresql+psycopg",
                username=self.DB_USER,
                password=self.DB_PASSWORD,
                host=self.DB_HOST,
                port=self.DB_PORT,
                database=self.DB_NAME,
                )
            )

    model_config = SettingsConfigDict(
        env_file=str(
            BASE_DIR / (".env.test" if APP_ENV == "test" else ".env")
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
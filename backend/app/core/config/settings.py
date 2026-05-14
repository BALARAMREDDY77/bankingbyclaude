"""
Centralized Configuration Management
=====================================
Uses Pydantic Settings for type-safe, environment-driven configuration.
All settings are loaded once at startup and shared via dependency injection.
"""

from enum import Enum
from functools import lru_cache
from typing import List

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(str, Enum):
    JSON = "json"
    CONSOLE = "console"


# ──────────────────────────────────────────────
# Sub-Settings Groups
# ──────────────────────────────────────────────

class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_", env_file=".env", extra="ignore")

    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    name: str = Field(default="banking_platform")
    user: str = Field(default="banking_user")
    password: str = Field(default="")
    pool_size: int = Field(default=20)
    max_overflow: int = Field(default=10)
    pool_timeout: int = Field(default=30)
    echo: bool = Field(default=False)

    @property
    def async_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    @property
    def sync_url(self) -> str:
        """Used by Alembic migrations (sync driver)."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env", extra="ignore")

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    password: str = Field(default="")
    db: int = Field(default=0)
    max_connections: int = Field(default=50)

    @property
    def url(self) -> str:
        if self.password:
            return f"redis://:{self.password}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LOG_", env_file=".env", extra="ignore")

    level: LogLevel = Field(default=LogLevel.INFO)
    format: LogFormat = Field(default=LogFormat.JSON)
    file_enabled: bool = Field(default=False)
    file_path: str = Field(default="/var/log/banking-platform/app.log")


class DocumentPipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOC_", env_file=".env", extra="ignore")

    # Storage backend: local | s3 | gcs | azure
    storage_backend: str = Field(default="local")
    local_storage_path: str = Field(default="/tmp/banking_docs")

    # S3 / MinIO
    s3_bucket: str = Field(default="banking-documents")
    s3_region: str = Field(default="ap-south-1")
    s3_endpoint_url: Optional[str] = Field(default=None)   # MinIO override
    s3_access_key: str = Field(default="")
    s3_secret_key: str = Field(default="")

    # OCR
    tesseract_cmd: str = Field(default="/usr/bin/tesseract")
    ocr_languages: str = Field(default="eng+hin")           # Tesseract lang codes
    ocr_dpi: int = Field(default=300)
    ocr_timeout_seconds: int = Field(default=60)

    # Pipeline
    max_pages_per_doc: int = Field(default=50)
    max_file_size_mb: int = Field(default=20)
    chunk_size_chars: int = Field(default=1000)
    chunk_overlap_chars: int = Field(default=200)
    processing_concurrency: int = Field(default=4)

    # Retry
    max_retries: int = Field(default=3)
    retry_delay_seconds: float = Field(default=2.0)

    # Celery
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")

    @property
    def ocr_languages_list(self) -> List[str]:
        return [l.strip() for l in self.ocr_languages.split("+")]


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    # JWT
    access_token_secret: str = Field(default="insecure-access-secret-change-me")
    refresh_token_secret: str = Field(default="insecure-refresh-secret-change-me")
    access_token_expire_minutes: int = Field(default=15)
    refresh_token_expire_days: int = Field(default=7)
    algorithm: str = Field(default="HS256")

    # Bcrypt
    bcrypt_rounds: int = Field(default=12)

    # Rate limiting (per IP, per minute)
    login_rate_limit: int = Field(default=5)          # max login attempts
    login_rate_window: int = Field(default=300)        # 5 minutes window
    api_rate_limit: int = Field(default=100)           # general API limit
    api_rate_window: int = Field(default=60)

    # Brute-force lockout
    max_failed_attempts: int = Field(default=5)
    lockout_duration_seconds: int = Field(default=900)  # 15 minutes

    # CSRF
    csrf_secret: str = Field(default="insecure-csrf-secret-change-me")
    csrf_token_expire_seconds: int = Field(default=3600)

    # Cookies
    cookie_secure: bool = Field(default=True)         # HTTPS only (False in dev)
    cookie_httponly: bool = Field(default=True)
    cookie_samesite: str = Field(default="lax")

    # File upload
    max_upload_size_mb: int = Field(default=10)
    allowed_mime_types: str = Field(
        default="image/jpeg,image/png,image/gif,application/pdf,text/csv"
    )

    @property
    def allowed_mime_types_list(self) -> List[str]:
        return [m.strip() for m in self.allowed_mime_types.split(",")]


class CORSSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CORS_", env_file=".env", extra="ignore")

    origins: str = Field(default="http://localhost:3000,http://localhost:5173")
    allow_credentials: bool = Field(default=True)

    @property
    def origins_list(self) -> List[str]:
        return [o.strip() for o in self.origins.split(",") if o.strip()]


# ──────────────────────────────────────────────
# Root Application Settings
# ──────────────────────────────────────────────

class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    app_env: Environment = Field(default=Environment.DEVELOPMENT, alias="APP_ENV")
    app_name: str = Field(default="Enterprise AI Banking Platform", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    app_secret_key: str = Field(default="insecure-dev-key", alias="APP_SECRET_KEY")

    # Server
    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    backend_workers: int = Field(default=1, alias="BACKEND_WORKERS")
    backend_reload: bool = Field(default=False, alias="BACKEND_RELOAD")

    # API
    api_v1_prefix: str = "/api/v1"
    docs_enabled: bool = True           # Disable in production if needed

    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    cors: CORSSettings = Field(default_factory=CORSSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    documents: DocumentPipelineSettings = Field(default_factory=DocumentPipelineSettings)

    @property
    def is_production(self) -> bool:
        return self.app_env == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.app_env == Environment.DEVELOPMENT

    @property
    def debug(self) -> bool:
        return self.app_env == Environment.DEVELOPMENT


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """
    Return cached application settings.
    Use as a FastAPI dependency: settings: AppSettings = Depends(get_settings)
    """
    return AppSettings()


# Convenience singleton — used in non-DI contexts (e.g., logging setup)
settings: AppSettings = get_settings()

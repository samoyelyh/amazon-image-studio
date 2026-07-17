from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import quote_plus

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("server/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Amazon Image Studio API"
    app_version: str = "0.3.0"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "amazon_image_studio"
    mysql_user: str = "amazon"
    mysql_password: SecretStr = SecretStr("change-me")
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_recycle_seconds: int = 1800
    database_url_override: SecretStr | None = None

    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    celery_broker_url: SecretStr | None = None
    celery_result_backend: SecretStr | None = None

    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr = SecretStr("minioadmin")
    s3_secret_key: SecretStr = SecretStr("change-me-now")
    s3_bucket: str = "amazon-image-studio"
    s3_secure: bool = False
    s3_presigned_url_ttl_seconds: int = 900

    health_check_timeout_seconds: float = 3.0

    jwt_secret: SecretStr = SecretStr("local-development-jwt-secret-change-me")
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "amazon-image-studio"
    jwt_audience: str = "amazon-image-studio-web"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_cookie_name: str = "ais_refresh_token"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: Literal["lax", "strict"] = "lax"
    bootstrap_admin_email: EmailStr | None = None
    bootstrap_admin_password: SecretStr | None = None
    bootstrap_admin_name: str = "Platform Administrator"
    bootstrap_organization_name: str = "Default Organization"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def validate_auth_security(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if len(secret) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        if self.environment == "production" and secret == "local-development-jwt-secret-change-me":
            raise ValueError("JWT_SECRET must be replaced in production")
        if self.environment == "production" and not self.refresh_cookie_secure:
            raise ValueError("REFRESH_COOKIE_SECURE must be enabled in production")
        if bool(self.bootstrap_admin_email) != bool(self.bootstrap_admin_password):
            raise ValueError("BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be configured together")
        if self.bootstrap_admin_password and len(self.bootstrap_admin_password.get_secret_value()) < 12:
            raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters")
        return self

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override.get_secret_value()
        password = quote_plus(self.mysql_password.get_secret_value())
        user = quote_plus(self.mysql_user)
        database = quote_plus(self.mysql_database)
        return f"mysql+asyncmy://{user}:{password}@{self.mysql_host}:{self.mysql_port}/{database}?charset=utf8mb4"

    @property
    def resolved_celery_broker_url(self) -> str:
        return (self.celery_broker_url or self.redis_url).get_secret_value()

    @property
    def resolved_celery_result_backend(self) -> str:
        return (self.celery_result_backend or self.redis_url).get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()

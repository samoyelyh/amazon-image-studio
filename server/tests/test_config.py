from pydantic import SecretStr
import pytest

from app.core.config import Settings


def test_database_url_encodes_credentials() -> None:
    settings = Settings(
        _env_file=None,
        mysql_host="mysql",
        mysql_port=3306,
        mysql_database="studio data",
        mysql_user="studio user",
        mysql_password=SecretStr("p@ss/word"),
    )

    assert settings.database_url == (
        "mysql+asyncmy://studio+user:p%40ss%2Fword@mysql:3306/studio+data?charset=utf8mb4"
    )


def test_cors_origins_accept_comma_separated_value() -> None:
    settings = Settings(_env_file=None, cors_origins="https://one.example, https://two.example")
    assert settings.cors_origins == ["https://one.example", "https://two.example"]


def test_celery_defaults_to_redis_url() -> None:
    settings = Settings(_env_file=None, redis_url=SecretStr("redis://redis:6379/5"))
    assert settings.resolved_celery_broker_url == "redis://redis:6379/5"
    assert settings.resolved_celery_result_backend == "redis://redis:6379/5"


def test_production_rejects_development_auth_secrets() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, environment="production", refresh_cookie_secure=True)


def test_production_requires_secure_refresh_cookie() -> None:
    with pytest.raises(ValueError, match="REFRESH_COOKIE_SECURE"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret=SecretStr("a-production-secret-with-more-than-32-characters"),
        )

from pydantic import SecretStr

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

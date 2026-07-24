from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings


@lru_cache
def get_redis_client() -> Redis:
    return Redis.from_url(
        get_settings().redis_url.get_secret_value(),
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
    )

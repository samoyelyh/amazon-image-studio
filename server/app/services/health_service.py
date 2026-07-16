import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.infrastructure.redis import get_redis_client
from app.schemas.health import ComponentHealth
from app.services.storage_service import get_storage_service


async def _measure(check: Callable[[], Awaitable[None]]) -> ComponentHealth:
    started = perf_counter()
    try:
        await asyncio.wait_for(check(), timeout=get_settings().health_check_timeout_seconds)
        return ComponentHealth(status="ok", latency_ms=round((perf_counter() - started) * 1000, 2))
    except Exception as error:  # Health responses intentionally expose only the exception type.
        return ComponentHealth(
            status="error",
            latency_ms=round((perf_counter() - started) * 1000, 2),
            message=type(error).__name__,
        )


async def _check_database() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_redis() -> None:
    if not await get_redis_client().ping():
        raise RuntimeError("Redis ping failed")


async def _check_storage() -> None:
    await asyncio.to_thread(get_storage_service().check_health)


async def check_dependencies() -> dict[str, ComponentHealth]:
    database, redis, storage = await asyncio.gather(
        _measure(_check_database),
        _measure(_check_redis),
        _measure(_check_storage),
    )
    return {"database": database, "redis": redis, "storage": storage}

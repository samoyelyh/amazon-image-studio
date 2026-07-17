from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.db.session import get_engine
from app.infrastructure.redis import get_redis_client


T = TypeVar("T")


def run_worker_coroutine(factory: Callable[[], Awaitable[T]]) -> T:
    """Run one Celery task with async clients scoped to its event loop."""
    get_engine.cache_clear()
    get_redis_client.cache_clear()

    async def runner() -> T:
        try:
            return await factory()
        finally:
            redis = get_redis_client()
            await redis.aclose()
            await get_engine().dispose()
            get_redis_client.cache_clear()
            get_engine.cache_clear()

    return asyncio.run(runner())

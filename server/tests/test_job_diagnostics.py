from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.job_diagnostics_service import (
    _actual_max_concurrency,
    _resource_capacity_summary,
)


def test_actual_max_concurrency_uses_real_provider_execution_windows() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    jobs = [
        SimpleNamespace(started_at=start, finished_at=start + timedelta(seconds=5)),
        SimpleNamespace(started_at=start + timedelta(seconds=1), finished_at=start + timedelta(seconds=4)),
        SimpleNamespace(started_at=start + timedelta(seconds=2), finished_at=start + timedelta(seconds=3)),
        SimpleNamespace(started_at=start + timedelta(seconds=5), finished_at=start + timedelta(seconds=6)),
        SimpleNamespace(started_at=None, finished_at=None),
    ]

    assert _actual_max_concurrency(jobs, start + timedelta(seconds=10)) == 3


def test_cooling_key_does_not_change_configured_resource_capacity() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    configured, available, pools, reasons = _resource_capacity_summary(
        [
            ("pool-1", "key-1", 10, now + timedelta(minutes=1), None),
        ],
        now,
    )

    assert configured == 10
    assert available == 0
    assert pools == ["pool-1"]
    assert reasons == ["1 个资源 Key 因上游错误临时冷却，恢复后将自动重试"]

from datetime import datetime, timezone

from app.workers.celery_app import celery_app


@celery_app.task(name="system.heartbeat", ignore_result=False)
def heartbeat() -> dict[str, str]:
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

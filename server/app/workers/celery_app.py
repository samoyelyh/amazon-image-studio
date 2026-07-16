from celery import Celery

from app.core.config import get_settings


settings = get_settings()
celery_app = Celery(
    "amazon_image_studio",
    broker=settings.resolved_celery_broker_url,
    backend=settings.resolved_celery_result_backend,
    include=["app.workers.tasks.system"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_send_sent_event=True,
    worker_send_task_events=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    result_expires=3600,
    task_default_queue="default",
    task_routes={
        "system.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "system-heartbeat": {
            "task": "system.heartbeat",
            "schedule": 60.0,
        }
    },
)

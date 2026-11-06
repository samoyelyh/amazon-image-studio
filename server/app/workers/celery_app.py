from celery import Celery

from app.core.config import get_settings


settings = get_settings()
import os
if os.environ.get('DSH_ENABLED','false').lower()=='true':
    from celery.signals import worker_process_init
    @worker_process_init.connect
    def install_native_guards(**kwargs):
        from app.agents.dsh_settings import state,call_limit
        from app.experiments.dsh.ledger import install_guards
        install_guards(state()/'worker',limit=call_limit(),native_only=True)
celery_app = Celery(
    "amazon_image_studio",
    broker=settings.resolved_celery_broker_url,
    backend=settings.resolved_celery_result_backend,
    include=["app.workers.tasks.system", "app.workers.tasks.jobs"],
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
    broker_transport_options={
        "visibility_timeout": max(1800, settings.job_timeout_seconds * 2),
    },
    task_time_limit=settings.job_timeout_seconds,
    task_soft_time_limit=max(1, settings.job_timeout_seconds - 15),
    result_expires=3600,
    task_default_queue="default",
    task_routes={
        "system.batch_queue_retention": {"queue": "queue_retention"},
        "system.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "system-heartbeat": {
            "task": "system.heartbeat",
            "schedule": 60.0,
        },
        "dispatch-due-jobs": {
            "task": "system.dispatch_due_jobs",
            "schedule": settings.job_dispatch_interval_seconds,
        },
        "continue-quick-listings": {
            "task": "system.continue_quick_listings",
            "schedule": 10.0,
        },
        "continue-batch-review-luna": {
            "task": "system.continue_batch_review_luna",
            "schedule": 30.0,
        },
        "recover-stale-jobs": {"task": "system.recover_stale_jobs", "schedule": 60.0},
        "release-expired-reservations": {"task": "system.release_expired_reservations", "schedule": 300.0},
        "batch-queue-retention": {"task": "system.batch_queue_retention", "schedule": 300.0},
    },
)

from app.workers.celery_app import celery_app
from app.workers.tasks.system import heartbeat


def test_celery_registers_maintenance_heartbeat() -> None:
    assert "system.heartbeat" in celery_app.tasks
    assert celery_app.conf.beat_schedule["system-heartbeat"]["task"] == "system.heartbeat"
    assert celery_app.conf.task_routes["system.*"]["queue"] == "maintenance"


def test_heartbeat_payload() -> None:
    result = heartbeat.run()
    assert result["status"] == "ok"
    assert result["timestamp"].endswith("+00:00")

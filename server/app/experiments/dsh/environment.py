import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STATE = ROOT / 'experiments' / 'dsh' / '.state'


def configure():
    """Read only this experiment's explicit environment; never load the source .env."""
    if not (STATE / 'runtime.json').is_file():
        raise RuntimeError('Run experiments/dsh/start.ps1 to initialize the isolated environment')
    for key, value in json.loads((STATE / 'runtime.json').read_text(encoding='utf-8')).items():
        os.environ[key] = str(value)
    from app.core.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    expected='sqlite+aiosqlite:///'+(STATE/'platform.sqlite').as_posix()
    if settings.environment != 'test' or settings.database_url != expected:
        raise RuntimeError('Refusing non-experiment database')
    if settings.resolved_celery_broker_url != 'redis://127.0.0.1:16489/1':
        raise RuntimeError('Refusing non-experiment broker')
    if settings.redis_url.get_secret_value()!='redis://127.0.0.1:16489/0' or settings.resolved_celery_result_backend!='redis://127.0.0.1:16489/2':
        raise RuntimeError('Refusing shared Redis resource/result state')
    from app.experiments.dsh.quota_lock import install
    install(STATE)
    return settings

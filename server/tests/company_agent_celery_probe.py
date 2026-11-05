"""Real Celery consumer on an isolated broker, with a mandatory Mock Provider."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import redis
import redis.asyncio as async_redis
from celery.signals import worker_ready
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from tests.company_agent_support import install_mock_worker, isolated_minio_storage


def main():
    url=os.environ['AGENT_COMPANY_TEST_DATABASE_URL'];parsed=urlsplit(url)
    if parsed.hostname!='127.0.0.1' or parsed.port==3306 or not parsed.path.startswith('/agent_company_test_'):
        raise RuntimeError('Refusing non-isolated database')
    data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    settings=Settings(_env_file=None,environment='test')
    engine=create_async_engine(url)
    resource_redis=async_redis.Redis.from_url('redis://127.0.0.1:16387/0',decode_responses=True)
    patch=pytest.MonkeyPatch()
    ctx={'settings':settings,'engine':engine,'redis':resource_redis,'storage':isolated_minio_storage()}
    worker=install_mock_worker(ctx,patch)
    # Keep original execute_job/run_worker_coroutine, but never let cleanup touch live clients.
    from app.workers import runtime
    for name in ('get_engine','get_redis_client'):
        getter=getattr(worker,name);getter.cache_clear=lambda:None
        patch.setattr(runtime,name,getter)
    from app.workers.celery_app import celery_app
    celery_app.conf.update(broker_url='redis://127.0.0.1:16387/6',result_backend='redis://127.0.0.1:16387/7')
    ready=redis.Redis.from_url('redis://127.0.0.1:16387/6',decode_responses=True)
    @worker_ready.connect(weak=False)
    def mark_ready(**kwargs):ready.set(os.environ['AGENT_COMPANY_TEST_WORKER_READY'],'ready',ex=120)
    try:
        celery_app.worker_main(['worker','--pool=solo','--concurrency=1','--loglevel=ERROR',
            '--queues=agent_company_probe','--hostname=agent-company-probe@localhost',
            '--without-heartbeat','--without-gossip','--without-mingle'])
    finally:
        ready.close();patch.undo()


if __name__=='__main__':main()

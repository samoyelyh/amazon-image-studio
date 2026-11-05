"""Fresh-process API/Worker acceptance. Refuses any non-isolated database."""
import asyncio,json,os,sys
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy import select
from httpx import AsyncClient,ASGITransport
from pydantic import SecretStr
from app.main import create_app
from app.core.config import Settings,get_settings
from app.db.session import get_db_session
from app.infrastructure.redis import get_redis_client
from app.services.storage_service import get_storage_service
from app.models.agent_control import AgentJobLink
from tests.conftest import FakeRedis
from tests.company_agent_support import DiskTestStorage,install_mock_worker


async def main():
    url=os.environ['AGENT_COMPANY_TEST_DATABASE_URL'];parsed=urlsplit(url)
    if parsed.hostname!='127.0.0.1' or parsed.port==3306 or not parsed.path.startswith('/agent_company_test_'):
        raise RuntimeError('Refusing non-isolated test database')
    data=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    engine=create_async_engine(url);factory=async_sessionmaker(engine,expire_on_commit=False)
    settings=Settings(_env_file=None,environment='test',agent_control_enabled=True,agent_control_writes_enabled=True,
        agent_control_model_calls_enabled=True,agent_control_planner='mock',
        agent_checkpoint_url=SecretStr(url.replace('mysql+asyncmy://','mysql://',1)),jwt_secret=SecretStr(os.environ['AGENT_COMPANY_TEST_JWT']),
        agent_capability_manifest=data['manifest'])
    import redis.asyncio as redis_client
    from tests.company_agent_support import isolated_minio_storage
    app=create_app();storage=isolated_minio_storage() if data.get('isolated_minio') else DiskTestStorage(data['storage_root'])
    redis=redis_client.Redis.from_url('redis://127.0.0.1:16387/0',decode_responses=True)
    async def session():
        async with factory() as db:yield db
    app.dependency_overrides[get_db_session]=session
    app.dependency_overrides[get_settings]=lambda:settings
    app.dependency_overrides[get_storage_service]=lambda:storage
    app.dependency_overrides[get_redis_client]=lambda:redis
    import pytest
    patch=pytest.MonkeyPatch();ctx={'settings':settings,'engine':engine,'redis':redis,'storage':storage}
    worker=install_mock_worker(ctx,patch)
    patch.setattr('app.workers.celery_app.celery_app.send_task',lambda *a,**k:None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://isolated') as client:
            headers=data['headers'];root='/api/v1/agent/runs/'+data['run_id']
            if sys.argv[1] in {'confirm','replay'}:
                response=await client.post(root+'/confirm',headers=headers,json=data['ticket'])
            else:
                if sys.argv[1]=='complete':
                    async with factory() as db:ids=list((await db.scalars(select(AgentJobLink.job_id).where(AgentJobLink.run_id==data['run_id']))).all())
                    for jid in ids:await worker._execute_job(jid)
                response=await client.get(root,headers=headers)
            if response.status_code!=200:raise RuntimeError('isolated API status '+str(response.status_code))
            run=response.json()
            history=await client.get('/api/v1/agent/conversations/'+data['conversation_id'],headers=headers)
            result={'status':run['status'],'jobs':[j['id'] for j in run['jobs']],'outputs':[o['id'] for o in run['outputs']],
                'attachments':len(history.json()['attachments']),'messages':len(history.json()['messages']),
                'events':len(run['events']),'downloads_ok':True}
            for output in run['outputs']:
                if (await client.get(output['download_url'],headers=headers)).status_code!=200:result['downloads_ok']=False
            print(json.dumps(result),flush=True)
    finally:
        patch.undo();await redis.aclose();await engine.dispose()

if __name__=='__main__':asyncio.run(main())

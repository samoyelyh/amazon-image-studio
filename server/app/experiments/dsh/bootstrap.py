"""Initialize only the named experiment DB. Reuse explicitly authorized provider configuration.

The production-side probe performs SELECTs in a read-only transaction and rewraps
one eligible API key per enabled provider. Plaintext keys never leave that process.
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess

from cryptography.fernet import Fernet
from app.experiments.dsh.environment import ROOT, STATE

EXPORT = r'''
import asyncio,json,sys,os
from pathlib import Path
from datetime import datetime,timezone
from cryptography.fernet import Fernet
from sqlalchemy import select,text,or_
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.core.config import get_settings
from app.db.session import get_engine
from app.models.tasks import Provider,ProviderModel,ApiKey,ModelCapability,ResourcePool,OperationResourcePool
from app.security.api_keys import decrypt_api_key
async def main():
 dest=Fernet(sys.stdin.read().strip().encode()); settings=get_settings()
 models=[]; providers={}
 async with async_sessionmaker(get_engine(),expire_on_commit=False)() as db:
  await db.execute(text('SET TRANSACTION READ ONLY'))
  for code in ['gpt-6.1-sol','gpt-6.1-terra','gpt-image-2']:
   rows=(await db.execute(select(ProviderModel,Provider,ResourcePool).join(Provider,Provider.id==ProviderModel.provider_id).join(ResourcePool,ResourcePool.model_id==ProviderModel.id).where(ProviderModel.code==code,ProviderModel.enabled.is_(True),Provider.enabled.is_(True),ResourcePool.enabled.is_(True)).order_by(ResourcePool.priority))).all()
   for model,provider,pool in rows:
    key=await db.scalar(select(ApiKey).where(ApiKey.provider_id==provider.id,ApiKey.enabled.is_(True),or_(ApiKey.status=='active',(ApiKey.status=='cooling') & (ApiKey.cooldown_until<=datetime.now(timezone.utc)))).order_by(ApiKey.max_concurrency.desc()))
    if not key:continue
    if provider.id not in providers:
     providers[provider.id]={'code':provider.code,'name':provider.name,'provider_type':provider.provider_type,'base_url':provider.base_url,'config':provider.config_json,'sealed_key':dest.encrypt(decrypt_api_key(settings,key.secret_ciphertext).encode()).decode(),'max_concurrency':min(4,key.max_concurrency)}
    caps=list((await db.scalars(select(ModelCapability.capability).where(ModelCapability.model_id==model.id))).all())
    models.append({'provider':provider.id,'code':model.code,'name':model.name,'upstream_model':model.upstream_model,'config':model.config_json,'capabilities':caps});break
  manifest=json.loads(Path(settings.agent_capability_manifest).read_text()) if settings.agent_capability_manifest else {}
  servers=[]
  for server in manifest.get('mcp_servers',[]):
   if server.get('enabled') and server.get('profile')=='sellersprite':
    env=server.get('credential_env');secret=os.environ.get(env,'')
    if secret:servers.append({'server':server,'sealed_credential':dest.encrypt(secret.encode()).decode()})
  await db.rollback()
 print(json.dumps({'providers':providers,'models':models,'mcp':servers}))
asyncio.run(main())
'''


def init_environment():
    STATE.mkdir(parents=True, exist_ok=True)
    config = STATE / 'runtime.json'
    if not config.exists():
        values = {
            'ENVIRONMENT':'test','DATABASE_URL_OVERRIDE':'sqlite+aiosqlite:///'+(STATE/'platform.sqlite').as_posix(),
            'REDIS_URL':'redis://127.0.0.1:16489/0','CELERY_BROKER_URL':'redis://127.0.0.1:16489/1','CELERY_RESULT_BACKEND':'redis://127.0.0.1:16489/2',
            'JWT_SECRET':secrets.token_urlsafe(48),'API_KEY_ENCRYPTION_KEY':Fernet.generate_key().decode(),
            'AGENT_CONTROL_ENABLED':'true','AGENT_CONTROL_WRITES_ENABLED':'true','AGENT_CONTROL_MODEL_CALLS_ENABLED':'true',
            'AGENT_CONTROL_PLANNER':'existing_text','AGENT_CONTROL_TEXT_MODEL':'gpt-6.1-sol','AGENT_CONTROL_DECISION_MODEL':'gpt-6.1-terra',
            'AGENT_CONTROL_DECISION_ENABLED':'true','AGENT_DYNAMIC_CAPABILITIES_ENABLED':'true','AGENT_APLUS_PROFESSIONAL_ENABLED':'true',
            'AGENT_CHECKPOINT_URL':'sqlite:///'+(STATE/'langgraph.sqlite').as_posix(),'AGENT_EXECUTION_MODE':'autonomous','AGENT_AUTO_EXECUTE_ENABLED':'true',
            'AGENT_AUTO_MAX_IMAGES':'4','AGENT_AUTO_MAX_CREDITS':'100','AGENT_AUTO_MAX_TEXT_JOBS':'2','JOB_MAX_ATTEMPTS':'1',
            'PROVIDER_REQUEST_TIMEOUT_SECONDS':'120','JOB_TIMEOUT_SECONDS':'240','JOB_HEARTBEAT_TIMEOUT_SECONDS':'90','ACCESS_TOKEN_TTL_MINUTES':'1440',
            'BOOTSTRAP_ADMIN_ACCOUNT':'dsh-admin','BOOTSTRAP_ADMIN_PASSWORD':secrets.token_urlsafe(18),'BOOTSTRAP_ORGANIZATION_NAME':'DSH Experiment',
            'BOOTSTRAP_ADMIN_NAME':'DSH Experiment Admin', 'BOOTSTRAP_QUOTA_BALANCE':'10000',
        }
        config.write_text(json.dumps(values,indent=2),encoding='utf-8')
        (STATE/'sidecar.token').write_text(secrets.token_urlsafe(48))
    values=json.loads(config.read_text(encoding='utf-8'))
    values.setdefault('REFRESH_COOKIE_NAME','ais_dsh_experiment_refresh')
    values.setdefault('JWT_ISSUER','ais-dsh-experiment')
    values.setdefault('JWT_AUDIENCE','ais-dsh-experiment-web')
    config.write_text(json.dumps(values,indent=2),encoding='utf-8')
    (STATE/'login.json').write_text(json.dumps({'account':values['BOOTSTRAP_ADMIN_ACCOUNT'],'password':values['BOOTSTRAP_ADMIN_PASSWORD']},indent=2),encoding='utf-8')
    return values


async def bootstrap(reuse=False):
    values = init_environment()
    from app.experiments.dsh.environment import configure
    settings=configure()
    from app.db.base import Base
    import app.models
    from app.db.session import get_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import select
    from app.cli.bootstrap_identity import bootstrap as identity
    from app.cli.bootstrap_billing import bootstrap as billing
    from app.models.identity import Organization, User
    from app.models.tasks import Provider,ProviderModel,ModelCapability,ResourcePool,ApiKey,OperationResourcePool,ResourcePoolKey
    from app.security.api_keys import api_key_fingerprint
    engine=get_engine()
    async with engine.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine,expire_on_commit=False)() as db:
        await identity(db);await billing(db);await db.commit()
        org=await db.scalar(select(Organization).where(Organization.slug=='dsh-experiment'))
        user=await db.scalar(select(User).where(User.account=='dsh-admin'))
        if reuse and not await db.scalar(select(Provider.id).limit(1)):
            result=subprocess.run(['docker','exec','-i','amazon-image-studio-backend-1','python','-c',EXPORT],
                input=values['API_KEY_ENCRYPTION_KEY'],capture_output=True,text=True,encoding='utf-8',check=True)
            bundle=json.loads(result.stdout)
            for source_id,p in bundle['providers'].items():
                row=Provider(code='dsh-'+p['code'],name=p['name'],provider_type=p['provider_type'],base_url=p['base_url'],config_json=p['config'])
                db.add(row);await db.flush()
                clear=Fernet(values['API_KEY_ENCRYPTION_KEY'].encode()).decrypt(p['sealed_key'].encode()).decode()
                key=ApiKey(provider_id=row.id,label='Explicitly authorized experiment reuse',secret_ciphertext=p['sealed_key'],fingerprint=api_key_fingerprint(clear),secret_suffix='hidden',max_concurrency=p['max_concurrency'])
                db.add(key);await db.flush()
                del clear
                for m in [m for m in bundle['models'] if m['provider']==source_id]:
                    model=ProviderModel(provider_id=row.id,code=m['code'],name=m['name'],upstream_model=m['upstream_model'],config_json=m['config'])
                    db.add(model);await db.flush()
                    for cap in m['capabilities']:db.add(ModelCapability(model_id=model.id,capability=cap))
                    pool=ResourcePool(model_id=model.id,code='dsh-'+m['code'],name=m['name']);db.add(pool);await db.flush()
                    db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.id))
                    ops=[('listing.plan','text_generation')] if m['code']!='gpt-image-2' else [(operation,c) for operation in ['listing.generate','aplus.generate'] for c in m['capabilities'] if c in {'image_generation','image_edit','multi_image_reference'}]
                    for op,cap in ops:db.add(OperationResourcePool(operation_code=op,resource_pool_id=pool.id,required_capability=cap))
            servers=[]
            for item in bundle['mcp']:
                server=item['server'];server.update(organizations=[org.id],users=[user.id],max_calls_per_run=2)
                values[server['credential_env']]=Fernet(values['API_KEY_ENCRYPTION_KEY'].encode()).decrypt(item['sealed_credential'].encode()).decode()
                servers.append(server)
            if servers:
                manifest=STATE/'capabilities.json';manifest.write_text(json.dumps({'schema_version':1,'mcp_servers':servers,'skills':[]}),encoding='utf-8')
                values['AGENT_CAPABILITY_MANIFEST']=str(manifest)
                (STATE/'runtime.json').write_text(json.dumps(values,indent=2),encoding='utf-8')
            await db.commit()
            print(json.dumps({'reused_models':[m['code'] for m in bundle['models']],'mcp_servers':len(servers),'production_writes':0}))
        # Idempotent repair for an interrupted initial bootstrap, only in this DB.
        for pool in (await db.scalars(select(ResourcePool))).all():
            model=await db.get(ProviderModel,pool.model_id)
            key=await db.scalar(select(ApiKey).where(ApiKey.provider_id==model.provider_id))
            if key and not await db.scalar(select(ResourcePoolKey.id).where(ResourcePoolKey.resource_pool_id==pool.id,ResourcePoolKey.api_key_id==key.id)):
                db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.id))
            if model.code=='gpt-image-2':
                caps=(await db.scalars(select(ModelCapability.capability).where(ModelCapability.model_id==model.id))).all()
                for cap in set(caps)&{'image_generation','image_edit','multi_image_reference'}:
                    if not await db.scalar(select(OperationResourcePool.id).where(OperationResourcePool.resource_pool_id==pool.id,OperationResourcePool.operation_code=='aplus.generate',OperationResourcePool.required_capability==cap)):
                        db.add(OperationResourcePool(resource_pool_id=pool.id,operation_code='aplus.generate',required_capability=cap))
        await db.commit()
        (STATE/'identity.json').write_text(json.dumps({'organization_id':org.id,'user_id':user.id}),encoding='utf-8')
        # The existing deployment injects this Docker secret in its entrypoint,
        # so it is intentionally absent from `docker exec`'s environment.
        if reuse and not values.get('AGENT_CAPABILITY_MANIFEST'):
            approval=ROOT.parent/'AI生图'/'server'/'config'/'ss-mcp.approval.json'
            secret_file=ROOT.parent/'AI生图'/'.env.ss-mcp.secret'
            if approval.is_file() and secret_file.is_file():
                approved=json.loads(approval.read_text(encoding='utf-8'))
                servers=[s for s in approved.get('mcp_servers',[]) if s.get('enabled') and s.get('profile')=='sellersprite']
                for server in servers:
                    server.update(organizations=[org.id],users=[user.id],max_calls_per_run=2)
                    values[server['credential_env']]=secret_file.read_text(encoding='utf-8').strip()
                if servers:
                    manifest=STATE/'capabilities.json';manifest.write_text(json.dumps({'schema_version':1,'mcp_servers':servers,'skills':[]}),encoding='utf-8')
                    values['AGENT_CAPABILITY_MANIFEST']=str(manifest)
                    (STATE/'runtime.json').write_text(json.dumps(values,indent=2),encoding='utf-8')
                    print('Existing approved MCP configured for experiment identities only; credentials omitted.')
    await engine.dispose()


if __name__=='__main__':
    import sys
    asyncio.run(bootstrap('--reuse-authorized-provider' in sys.argv))

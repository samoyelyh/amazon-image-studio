"""Register the user's Kimi credential encrypted in the isolated resource pool.

No network requests or budget changes. Never reads production credentials.
"""
import asyncio
from datetime import datetime
import getpass
import json
import os
import re
import sqlite3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.experiments.dsh.environment import STATE,configure

def local_proxy():
    if os.name!='nt':return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as k:
            enabled=winreg.QueryValueEx(k,'ProxyEnable')[0];server=winreg.QueryValueEx(k,'ProxyServer')[0]
        if enabled and re.fullmatch(r'127\.0\.0\.1:\d+',server):return 'http://'+server
    except OSError:pass
    return None

async def main():
    settings=configure()
    from app.db.session import get_engine
    import app.models
    from app.models.identity import Organization
    from app.models.tasks import Provider,ProviderModel,ApiKey,ResourcePool,ResourcePoolKey,ModelCapability,OperationResourcePool
    from app.security.api_keys import encrypt_api_key,api_key_fingerprint
    key=getpass.getpass('Kimi Code key (encrypted experiment storage only): ').strip()
    if not key.startswith('sk-kimi-'):raise ValueError('Expected the Kimi Code credential explicitly supplied for this experiment')
    source=sqlite3.connect(STATE/'platform.sqlite');backup=STATE/'backups'/('before-kimi-k28-'+datetime.now().strftime('%Y%m%d%H%M%S')+'.sqlite');backup.parent.mkdir(exist_ok=True)
    dest=sqlite3.connect(backup);source.backup(dest);dest.close();source.close()
    async with async_sessionmaker(get_engine(),expire_on_commit=False)() as db:
        org=await db.scalar(select(Organization).where(Organization.slug=='dsh-experiment'))
        if not org:raise RuntimeError('Experiment organization is missing')
        provider=await db.scalar(select(Provider).where(Provider.code=='dsh-kimi-code'))
        if not provider:
            provider=Provider(code='dsh-kimi-code',name='Kimi Code experiment',provider_type='openai_compatible',base_url='https://api.kimi.com/coding/v1',config_json={});db.add(provider);await db.flush()
        provider.config_json={**provider.config_json,'preserve_reasoning':True,**({'http_proxy':local_proxy()} if local_proxy() else {})}
        credential=await db.scalar(select(ApiKey).where(ApiKey.fingerprint==api_key_fingerprint(key)))
        if not credential:
            credential=ApiKey(provider_id=provider.id,organization_id=org.id,label='User-authorized Kimi Code experiment',secret_ciphertext=encrypt_api_key(settings,key),fingerprint=api_key_fingerprint(key),secret_suffix='hidden',max_concurrency=2);db.add(credential);await db.flush()
        if credential.provider_id!=provider.id:raise RuntimeError('Credential is already registered under a different provider')
        del key
        model=await db.scalar(select(ProviderModel).where(ProviderModel.provider_id==provider.id,ProviderModel.code=='kimi-for-coding'))
        if not model:
            model=ProviderModel(provider_id=provider.id,code='kimi-for-coding',name='Kimi K2.8 Preview',upstream_model='kimi-for-coding',config_json={});db.add(model);await db.flush()
        for capability in ['text_generation','vision_input']:
            if not await db.scalar(select(ModelCapability.id).where(ModelCapability.model_id==model.id,ModelCapability.capability==capability)):
                db.add(ModelCapability(model_id=model.id,capability=capability))
        pool=await db.scalar(select(ResourcePool).where(ResourcePool.organization_id==org.id,ResourcePool.code=='dsh-kimi-k28'))
        if not pool:
            pool=ResourcePool(organization_id=org.id,model_id=model.id,code='dsh-kimi-k28',name='DSH K2.8 text and vision');db.add(pool);await db.flush()
        if not await db.scalar(select(ResourcePoolKey.id).where(ResourcePoolKey.resource_pool_id==pool.id,ResourcePoolKey.api_key_id==credential.id)):
            db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=credential.id))
        if not await db.scalar(select(OperationResourcePool.id).where(OperationResourcePool.resource_pool_id==pool.id,OperationResourcePool.operation_code=='listing.plan',OperationResourcePool.required_capability=='text_generation')):
            db.add(OperationResourcePool(organization_id=org.id,operation_code='listing.plan',resource_pool_id=pool.id,required_capability='text_generation'))
        await db.commit()
    print(json.dumps({'configured_model':'kimi-for-coding','version':'K2.8 Preview','reasoning_effort':'low','roles':['main','executor','vision'],'credential_storage':'encrypted isolated database','network_requests':0}))

if __name__=='__main__':asyncio.run(main())

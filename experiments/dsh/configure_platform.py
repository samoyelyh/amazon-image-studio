"""Add K2.8 resource bindings and two acceptance identities; existing records untouched."""
import asyncio,json
from pathlib import Path
from sqlalchemy import select,text
from uuid import uuid4
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.db.session import get_engine
from app.models.identity import Organization,User,Role,OrganizationMember
from app.models.tasks import Provider,ProviderModel,ApiKey,ResourcePool,ResourcePoolKey,OperationResourcePool,ModelCapability
from app.security.passwords import hash_password

async def main():
    config=json.loads(Path('/config/kimi.json').read_text())
    async with async_sessionmaker(get_engine(),expire_on_commit=False)() as db:
        org=await db.scalar(select(Organization).where(Organization.slug=='default-organization'))
        assert org
        provider=await db.scalar(select(Provider).where(Provider.code=='dsh-kimi-code'))
        if not provider:
            provider=Provider(code='dsh-kimi-code',name='DSH Kimi Code K2.8',provider_type='openai_compatible',base_url='https://api.kimi.com/coding/v1',config_json={'preserve_reasoning':True,'http_proxy':'http://host.docker.internal:7897'});db.add(provider);await db.flush()
        key=await db.scalar(select(ApiKey).where(ApiKey.fingerprint==config['fingerprint']))
        if not key:
            key=ApiKey(provider_id=provider.id,organization_id=org.id,label='DSH K2.8 user-authorized',secret_ciphertext=config['ciphertext'],fingerprint=config['fingerprint'],secret_suffix='hidden',max_concurrency=3);db.add(key);await db.flush()
        assert key.provider_id==provider.id
        model=await db.scalar(select(ProviderModel).where(ProviderModel.code=='kimi-for-coding',ProviderModel.provider_id==provider.id))
        if not model:
            model=ProviderModel(provider_id=provider.id,code='kimi-for-coding',name='Kimi K2.8 Preview',upstream_model='kimi-for-coding',config_json={});db.add(model);await db.flush()
        for cap in ['text_generation','vision_input']:
            if not await db.scalar(select(ModelCapability.id).where(ModelCapability.model_id==model.id,ModelCapability.capability==cap)):db.add(ModelCapability(model_id=model.id,capability=cap))
        pool=await db.scalar(select(ResourcePool).where(ResourcePool.organization_id==org.id,ResourcePool.code=='dsh-kimi-k28'))
        if not pool:
            pool=ResourcePool(organization_id=org.id,model_id=model.id,code='dsh-kimi-k28',name='DSH K2.8 native Sessions');db.add(pool);await db.flush()
        if not await db.scalar(select(ResourcePoolKey.id).where(ResourcePoolKey.resource_pool_id==pool.id,ResourcePoolKey.api_key_id==key.id)):db.add(ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key.id))
        if not await db.scalar(select(OperationResourcePool.id).where(OperationResourcePool.resource_pool_id==pool.id,OperationResourcePool.operation_code=='listing.plan',OperationResourcePool.required_capability=='text_generation')):
            await db.execute(text("INSERT INTO operation_resource_pools (id,organization_id,operation_code,resource_pool_id,required_capability,enabled,priority,created_at,updated_at) VALUES (:id,:org,'listing.plan',:pool,'text_generation',1,100,NOW(),NOW())"),{'id':str(uuid4()),'org':org.id,'pool':pool.id})
        for login in config['logins']:
            user=await db.scalar(select(User).where(User.account==login['account']))
            if not user:
                role=await db.scalar(select(Role).where(Role.code=='platform_admin')) if login['admin'] else None
                user=User(account=login['account'],display_name='DSH 验收账号',password_hash=hash_password(login['password']),platform_role_id=role.id if role else None);db.add(user);await db.flush()
                orgrole=await db.scalar(select(Role).where(Role.code=='organization_admin' if login['admin'] else Role.code=='member'))
                if not orgrole:orgrole=await db.scalar(select(Role).where(Role.code=='organization_member'))
                assert orgrole
                db.add(OrganizationMember(organization_id=org.id,user_id=user.id,role_id=orgrole.id))
        await db.commit()
    print(json.dumps({'resource_model':'kimi-for-coding','existing_credentials_changed':False,'acceptance_accounts':2,'provider_calls':0}))
if __name__=='__main__':asyncio.run(main())

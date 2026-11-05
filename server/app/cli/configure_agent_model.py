"""Explicit administrator configuration, no model inference or secret output.

Adds a lower-priority binding for an Agent-only model pin and reuses existing
Key IDs, so concurrency counters and quota rules are not duplicated.
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_engine
from app.models.tasks import Provider, ProviderModel, ModelCapability, ResourcePool, ResourcePoolKey, OperationResourcePool, ApiKey
from app.services.resource_pool_service import resolve_operation_model_code


async def configure(db, organization_id, *, apply=False):
    now=datetime.now(timezone.utc)
    timestamps={'created_at':now,'updated_at':now}
    source = await db.scalar(select(ResourcePool).where(ResourcePool.code=='aso8ty-text-channel-2',
        ResourcePool.organization_id.is_(None),ResourcePool.enabled.is_(True)).with_for_update())
    if source is None:raise ValueError('Existing approved text pool missing')
    source_model = await db.get(ProviderModel,source.model_id)
    provider = await db.get(Provider,source_model.provider_id)
    if not provider.enabled or provider.code!='aso8ty-openai-channel-2' or provider.base_url.rstrip('/')!='https://api.aso8ty.com/v1':
        raise ValueError('Approved provider does not match')
    keys=list((await db.execute(select(ResourcePoolKey,ApiKey.id).join(ApiKey,ApiKey.id==ResourcePoolKey.api_key_id)
        .where(ResourcePoolKey.resource_pool_id==source.id,ResourcePoolKey.enabled.is_(True),
            ApiKey.provider_id==provider.id,ApiKey.enabled.is_(True),ApiKey.status=='active'))).all())
    if not keys:raise ValueError('Approved pool has no active key')
    before=await resolve_operation_model_code(db,organization_id=organization_id,operation_code='listing.plan',capability='text_generation')
    created=[]
    model=await db.scalar(select(ProviderModel).where(ProviderModel.provider_id==provider.id,ProviderModel.code=='gpt-6.1-sol'))
    if model is None:
        model=ProviderModel(provider_id=provider.id,code='gpt-6.1-sol',upstream_model='gpt-6.1-sol',
            name='GPT-6.1 Sol · Agent reasoning',config_json={'chat_endpoint':'/chat/completions'},**timestamps)
        db.add(model);await db.flush();created.append({'table':'models','id':model.id})
        for capability in ('text_generation','vision_input'):
            item=ModelCapability(model_id=model.id,capability=capability,created_at=now);db.add(item)
    elif not model.enabled or model.upstream_model!='gpt-6.1-sol':
        raise ValueError('Existing target model needs administrator review')
    await db.flush()
    caps=set((await db.scalars(select(ModelCapability.capability).where(ModelCapability.model_id==model.id))).all())
    if not {'text_generation','vision_input'}<=caps:raise ValueError('Target model capabilities incomplete')
    pool=await db.scalar(select(ResourcePool).where(ResourcePool.code=='aso8ty-agent-sol',ResourcePool.organization_id.is_(None)))
    if pool is None:
        pool=ResourcePool(model_id=model.id,code='aso8ty-agent-sol',name='ASO8TY Agent Sol',priority=10000,**timestamps)
        db.add(pool);await db.flush();created.append({'table':'resource_pools','id':pool.id})
    elif pool.model_id!=model.id or not pool.enabled or pool.priority!=10000:
        raise ValueError('Existing target pool needs administrator review')
    for link,key_id in keys:
        existing=await db.scalar(select(ResourcePoolKey).where(ResourcePoolKey.resource_pool_id==pool.id,ResourcePoolKey.api_key_id==key_id))
        if existing is None:
            item=ResourcePoolKey(resource_pool_id=pool.id,api_key_id=key_id,priority=link.priority,weight=link.weight,**timestamps)
            db.add(item);await db.flush();created.append({'table':'resource_pool_keys','id':item.id})
        elif not existing.enabled:raise ValueError('Existing target key link disabled')
    operation=await db.scalar(select(OperationResourcePool).where(OperationResourcePool.resource_pool_id==pool.id,
        OperationResourcePool.operation_code=='listing.plan',OperationResourcePool.required_capability=='text_generation',
        OperationResourcePool.organization_id.is_(None)))
    if operation is None:
        operation=OperationResourcePool(resource_pool_id=pool.id,operation_code='listing.plan',required_capability='text_generation',priority=10000,**timestamps)
        db.add(operation);await db.flush();created.append({'table':'operation_resource_pools','id':operation.id})
    elif not operation.enabled or operation.priority!=10000:raise ValueError('Existing target operation needs review')
    selected=await resolve_operation_model_code(db,organization_id=organization_id,operation_code='listing.plan',
        capability='text_generation',additional_capabilities={'vision_input'},preferred_model_code='gpt-6.1-sol')
    after=await resolve_operation_model_code(db,organization_id=organization_id,operation_code='listing.plan',capability='text_generation')
    if before!=after:raise ValueError('Configuration would change the existing workspace default')
    result={'applied':apply,'model_code':selected,'provider_code':provider.code,'pool_id':pool.id,
        'shared_existing_key_count':len(keys),'existing_default_before':before,'existing_default_after':after,
        'created_rows':created,'paid_request_count':0}
    if apply:await db.commit()
    else:await db.rollback()
    return result


async def main(args):
    try:
        async with AsyncSession(get_engine(),expire_on_commit=False) as db:
            result=await configure(db,args.organization_id,apply=args.apply)
        print(json.dumps(result))
    finally:await get_engine().dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--organization-id',required=True)
    parser.add_argument('--apply',action='store_true')
    try:asyncio.run(main(parser.parse_args()))
    except Exception as error:
        print(json.dumps({'applied':False,'error_type':type(error).__name__}))
        raise SystemExit(1) from None

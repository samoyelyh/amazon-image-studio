"""Bounded paid reads through the existing gateway and durable tool audit.

A timeout keeps the reserved allowance; unknown chargedUnits is never reported as zero.
No automatic retry. Server credentials never enter the request/receipt objects.
"""
from datetime import datetime, timezone, timedelta
import math
from sqlalchemy import select
from app.core.errors import AppError
from app.agents.capabilities.registry import CapabilityRegistry, digest
from app.agents.capabilities.contracts import ExecutionContext
from app.agents.capabilities.mcp_gateway import MCPGateway
from app.models.hermes_agent import HermesToolAudit
from app.models.identity import Organization

ALLOWED_TOOLS={'asin.list','asin.detail','asin.content.list','keyword.asin.list','asin.review.list','category.ai.feature.list'}


def usable_data(result):
    # Includes legacy receipts recorded before the explicit flag existed.
    return (result.get('status') in {'succeeded','needs_review'} and not result.get('over_budget')
        and isinstance(result.get('content'),dict) and bool(result['content']))


def quote(registry, cap, arguments):
    server=registry.mcp.get(cap.binding)
    name=cap.id.split('.',2)[-1]
    tool=next((t for t in server.tools if t.name==name),None) if server else None
    if not server or server.profile!='sellersprite' or name not in ALLOWED_TOOLS or not tool or not tool.max_charge_units:
        raise AppError('agent.research_not_approved','该调研工具或计费上限尚未审批。',403)
    MCPGateway(registry).check_arguments(cap,arguments)
    return {'max_charge_units':tool.max_charge_units,'max_calls':1,'sufficient':True,
        'note':'上限为管理员审核的本次参数约束；实际chargedUnits取服务端回执，未知时不显示0。'}


async def receipts(db, conv):
    rows=(await db.scalars(select(HermesToolAudit).where(HermesToolAudit.organization_id==conv.organization_id,
        HermesToolAudit.user_id==conv.user_id,HermesToolAudit.conversation_id==conv.id,
        HermesToolAudit.tool_name=='amazon.research').order_by(HermesToolAudit.created_at.desc()).limit(15))).all()
    return [{'id':r.id,'status':r.status,**r.result_json,'data_available':usable_data(r.result_json)} for r in rows]


async def execute(db, settings, conv, permissions, args, action_key):
    ctx=ExecutionContext(conv.organization_id,conv.user_id,conv.id,action_key,frozenset(permissions))
    registry=CapabilityRegistry(settings,ctx);cap=registry.get(args.capability_id)
    price=quote(registry,cap,args.arguments);server=registry.mcp[cap.binding]
    if args.max_charge_units!=price['max_charge_units']:raise AppError('agent.price_changed','调研预算已变化，请重新确认。',409)
    now=datetime.now(timezone.utc)
    # Shared existing organization row serializes budget/dedup reservations across workers.
    await db.scalar(select(Organization).where(Organization.id==conv.organization_id).with_for_update())
    rows=(await db.scalars(select(HermesToolAudit).where(HermesToolAudit.organization_id==conv.organization_id,
        HermesToolAudit.tool_name=='amazon.research',HermesToolAudit.created_at>=now-timedelta(days=1)))).all()
    fingerprint=digest([ctx.organization_id,ctx.user_id,server.id,server.version,cap.id,cap.input_schema,args.arguments])
    for row in rows:
        result=row.result_json
        if result.get('request_key')==action_key:
            if row.status=='succeeded' or usable_data(result):return {**result,'data_available':usable_data(result)}
            raise AppError('agent.research_unknown','本次调用已发送或状态未知，禁止重复计费重发。',409)
        created=row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
        if result.get('fingerprint')==fingerprint and created>now-timedelta(hours=1):
            if row.status=='succeeded' or usable_data(result):return {**result,'data_available':usable_data(result),'cache_hit':True,'charged_this_call':0}
            raise AppError('agent.research_unknown','相同查询仍在执行或费用未知，请核对回执。',409)
    relevant=[r for r in rows if r.result_json.get('server_id')==server.id]
    if sum(r.result_json.get('reserved_units',0) for r in relevant)+args.max_charge_units>server.daily_unit_limit:
        raise AppError('agent.research_budget','组织24小时调研预留预算已用完。',409)
    minute=[r for r in relevant if (r.created_at.replace(tzinfo=timezone.utc) if r.created_at.tzinfo is None else r.created_at)>now-timedelta(minutes=1)]
    if len(minute)>=server.calls_per_minute:raise AppError('agent.research_rate','调研速率达到上限，请稍后再试。',429)
    same_run=[r for r in relevant if r.result_json.get('request_key','').split(':')[:2]==action_key.split(':')[:2]]
    if len(same_run)>=server.max_calls_per_run:raise AppError('agent.mcp_budget_exhausted','本次Run调研次数已达到上限。',409)
    result={'request_key':action_key,'fingerprint':fingerprint,'server_id':server.id,'tool':cap.id,
        'reserved_units':args.max_charge_units,'chargedUnits':None,'collected_at':now.isoformat(),
        'query_scope':args.arguments,'cache_hit':False,'status':'pending'}
    row=HermesToolAudit(conversation_id=conv.id,organization_id=ctx.organization_id,user_id=ctx.user_id,
        tool_name='amazon.research',arguments_json=args.arguments,result_json=result,status='pending',created_at=now)
    db.add(row);await db.flush();await db.commit() # Unknown remote outcome must survive process failure.
    try:
        value=await MCPGateway(registry).call(cap,args.arguments,calls_used=len(same_run),charge_confirmed=True)
        units=value.get('chargedUnits')
        known=isinstance(units,(int,float)) and not isinstance(units,bool) and math.isfinite(units) and units>=0
        receipt_status='succeeded' if known and units<=args.max_charge_units else 'needs_review'
        result={**result,'status':receipt_status,'chargedUnits':units if known else None,'receipt_status':'known' if known else 'unknown',
            'reserved_units':max(args.max_charge_units,units) if known else args.max_charge_units,
            'content':value['content'],'over_budget':bool(known and units>args.max_charge_units),
            'data_available':isinstance(value.get('content'),dict) and bool(value['content']) and not (known and units>args.max_charge_units)}
        row.status=receipt_status
    except AppError as error:
        result={**result,'status':'unknown','error_code':error.code,'receipt_status':'unknown'};row.status='unknown'
    row.result_json=result;await db.commit()
    return result

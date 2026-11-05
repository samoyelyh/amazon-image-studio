"""Private, scoped experience in existing durable Hermes records; no new memory database."""
from datetime import datetime, timezone
import re
from uuid import NAMESPACE_URL,uuid5
from pydantic import Field
from sqlalchemy import select
from app.agents.contracts import StrictModel
from app.core.errors import AppError
from app.models.hermes_agent import HermesConversation,HermesMessage


class MemoryQuery(StrictModel):
    product_type:str=Field(default='garment',max_length=60)
    scenario:str=Field(default='all',max_length=60)


class PreferenceChange(MemoryQuery):
    action:str=Field(pattern='^(remember|forget|task_only)$')
    key:str=Field(default='background_brightness',pattern='^(background_brightness|composition|visual_style|generation_habit|review_preference)$')
    value:str=Field(default='',max_length=500)
    expected_revision:int|None=Field(default=None,ge=0)
    plan_id:str|None=Field(default=None,min_length=36,max_length=36)


def scope(text):
    return 'jersey' if re.search(r'球衣|jersey|橄榄球',text,re.I) else 'garment'


def task_only(text):
    return bool(re.search(r'不用记|不要记|无需记|不必记|仅本次|只是特殊要求|只对这次',text))


async def store(db,conv):
    sid=str(uuid5(NAMESPACE_URL,f'agent-memory:{conv.organization_id}:{conv.user_id}'))
    values=dict(id=sid,organization_id=conv.organization_id,user_id=conv.user_id,
        controller_type='langgraph',mode='memory',status='active',title='个人创作经验')
    # A dedicated existing conversation row serializes only this user's memory writes.
    # Atomic creation avoids racing first writes and avoids User/business-conversation lock inversion.
    dialect=db.get_bind().dialect.name
    if dialect=='mysql':
        from sqlalchemy.dialects.mysql import insert
        statement=insert(HermesConversation).values(**values).on_duplicate_key_update(id=sid)
    elif dialect=='sqlite':
        from sqlalchemy.dialects.sqlite import insert
        statement=insert(HermesConversation).values(**values).on_conflict_do_nothing(index_elements=['id'])
    else:raise AppError('agent.memory_store_unsupported','当前数据库未验证个人经验写入。',503)
    await db.execute(statement)
    row=await db.scalar(select(HermesConversation).where(HermesConversation.id==sid,HermesConversation.organization_id==conv.organization_id,
        HermesConversation.user_id==conv.user_id,HermesConversation.mode=='memory').with_for_update().execution_options(populate_existing=True))
    if row is None:raise AppError('agent.memory_store_conflict','个人经验记录冲突，未更新。',409)
    return row


async def recall(db,conv,query):
    sid=str(uuid5(NAMESPACE_URL,f'agent-memory:{conv.organization_id}:{conv.user_id}'))
    ids=list((await db.scalars(select(HermesMessage.id).where(HermesMessage.conversation_id==sid,
        HermesMessage.organization_id==conv.organization_id,HermesMessage.user_id==conv.user_id)
        .order_by(HermesMessage.created_at.desc(),HermesMessage.id.desc()).limit(200))).all())
    rows=list((await db.scalars(select(HermesMessage).where(HermesMessage.id.in_(ids)))).all()) if ids else []
    matches=[r for r in rows if r.metadata_json.get('product_type') in ('all',query.product_type)
        and (query.scenario=='all' or r.metadata_json.get('scenario') in ('all',query.scenario))]
    preferences=[{'id':r.id,**r.metadata_json} for r in matches if r.role=='user_preference' and r.metadata_json.get('status')=='active']
    cases=[{'id':r.id,**r.metadata_json} for r in matches if r.role=='success_case']
    preferences.sort(key=lambda r:r.get('updated_at',''),reverse=True)
    cases.sort(key=lambda r:r.get('approved_at',''),reverse=True)
    return {'preferences':preferences[:20],'successful_cases':cases[:8],'privacy':'private_user','source':'durable_business_store'}


async def change(db,conv,args,*,human_request,source_run_id=None):
    if args.action=='task_only':
        if not task_only(human_request):raise AppError('agent.memory_consent','请明确说明本次不用记住。',409)
        query=select(HermesMessage.id).where(HermesMessage.conversation_id==conv.id,
            HermesMessage.organization_id==conv.organization_id,HermesMessage.user_id==conv.user_id,
            HermesMessage.role=='production_plan')
        if args.plan_id:query=query.where(HermesMessage.id==args.plan_id)
        target=await db.scalar(query.order_by(HermesMessage.created_at.desc(),HermesMessage.id.desc()).limit(1))
        if args.plan_id and not target:raise AppError('agent.production_plan_not_found','当前任务不存在或无权访问。',404)
        if target:
            row=await db.scalar(select(HermesMessage).where(HermesMessage.id==target).with_for_update().execution_options(populate_existing=True))
            row.metadata_json={**row.metadata_json,'memory_opt_out':True}
        return {'task_only':True,'cards':[{'type':'memory_receipt','message':'本次要求仅用于当前任务，不学习为长期偏好。'}]}
    if task_only(human_request):raise AppError('agent.memory_opt_out','本次已要求不记录长期偏好。',409)
    if not re.search(r'以后|今后|记住|长期|不要使用之前|删除.*偏好|忘记|不再使用',human_request):
        raise AppError('agent.memory_consent','未检测到长期偏好的明确表达，本次只作为任务要求。',409)
    if args.product_type=='all' and scope(human_request)=='jersey':raise AppError('agent.memory_scope','球衣偏好不能扩大为所有商品。',422)
    if args.key=='background_brightness' and args.action=='remember' and args.value not in ('brighter','neutral','darker'):
        raise AppError('agent.memory_value','背景亮度仅支持brighter/neutral/darker。',422)
    if args.key in ('generation_habit','review_preference') and args.action=='remember' and args.value not in ('samples_first','direct_production'):
        raise AppError('agent.memory_value','生成与审核习惯使用samples_first或direct_production。',422)
    if args.key!='background_brightness' and args.action=='remember' and re.search(r'号码|背号|logo|队徽|图案|(?:球衣|服装|衣服).*(?:改|换|变|红|蓝|黑|白|绿|黄|紫)|(?:改|换).*(?:球衣|服装|衣服).*色',args.value,re.I):
        raise AppError('agent.memory_product_facts','个人风格不能改写商品颜色、Logo或号码。',422)
    if args.action=='remember' and not args.value.strip():raise AppError('agent.memory_value','需要明确的偏好内容。',422)
    owner=await store(db,conv)
    mid=str(uuid5(NAMESPACE_URL,f'{owner.id}:{args.product_type}:{args.scenario}:{args.key}'))
    row=await db.scalar(select(HermesMessage).where(HermesMessage.id==mid).with_for_update().execution_options(populate_existing=True))
    prior=dict(row.metadata_json) if row else {}
    revision=prior.get('revision',0)
    if args.expected_revision is not None and args.expected_revision!=revision:
        raise AppError('agent.revision_conflict','偏好已更新，请读取后再修改。',409)
    now=datetime.now(timezone.utc).isoformat()
    data={'key':args.key,'value':args.value if args.action=='remember' else prior.get('value',''),
        'product_type':args.product_type,'scenario':args.scenario,'status':'active' if args.action=='remember' else 'inactive',
        'revision':revision+1,'source':'explicit_user','source_run_id':source_run_id,'updated_at':now,
        'history':[*prior.get('history',[]),{k:prior.get(k) for k in ('revision','value','status','updated_at')}][-20:]}
    if row:row.metadata_json=data;row.content=data['value']
    else:
        row=HermesMessage(id=mid,conversation_id=owner.id,organization_id=conv.organization_id,user_id=conv.user_id,
            role='user_preference',content=data['value'],metadata_json=data,created_at=datetime.now(timezone.utc));db.add(row)
    await db.flush()
    return {'preference':{'id':mid,**data},'cards':[{'type':'memory_receipt','message':'已更新个人偏好。' if args.action=='remember' else '已停用这项个人偏好。'}]}


def correction_rule(notes):
    if re.search(r'暗|提亮|亮一点|曝光',notes):return '适当提亮背景和环境曝光，保持当前服装本身真实颜色及商品设计不变。'
    if re.search(r'号码|背号|文字|姓名',notes):return '文字和号码严格对应当前组合的服装参考，不得沿用样图服装的具体文字或号码。'
    if re.search(r'背景.*乱|杂乱',notes):return '简化背景杂乱元素，保留目标人物、商品和主要场景关系。'
    if re.search(r'颜色|图案|Logo|队徽',notes,re.I):return '服装颜色、图案和Logo严格以本组合服装参考为准，不从其他样图继承设计。'
    return ''  # Unclassified feedback stays local to this sample, never an invented global rule.


async def record_case(db,conv,*,plan_id,template_id,product_type,scenario,before_output_id,after_output_id,notes,rule,opt_out=False):
    if opt_out:return None
    owner=await store(db,conv)
    mid=str(uuid5(NAMESPACE_URL,f'{owner.id}:case:{plan_id}:{template_id}:{after_output_id}'))
    if await db.scalar(select(HermesMessage.id).where(HermesMessage.id==mid).with_for_update()):return mid
    data={'plan_id':plan_id,'template_id':template_id,'product_type':product_type,'scenario':scenario,
        'before_output_id':before_output_id,'after_output_id':after_output_id,'notes':notes,'reusable_rule':rule,
        'approved_at':datetime.now(timezone.utc).isoformat(),'human_approved':True}
    db.add(HermesMessage(id=mid,conversation_id=owner.id,organization_id=conv.organization_id,user_id=conv.user_id,
        role='success_case',content=rule or '样图审核通过',metadata_json=data,created_at=datetime.now(timezone.utc)))
    await db.flush()
    # Only repeated successful corrections across independent plans may become an inferred preference.
    if '提亮背景' in rule:
        remembered=await recall(db,conv,MemoryQuery(product_type=product_type,scenario=scenario))
        cases=[c for c in remembered['successful_cases'] if '提亮背景' in c.get('reusable_rule','')]
        if len({c['plan_id'] for c in cases})>=3:
            pid=str(uuid5(NAMESPACE_URL,f'{owner.id}:{product_type}:{scenario}:background_brightness'))
            existing=await db.scalar(select(HermesMessage.id).where(HermesMessage.id==pid).with_for_update())
            if existing is None:  # Explicit preferences and tombstones always win.
                db.add(HermesMessage(id=pid,conversation_id=owner.id,organization_id=conv.organization_id,user_id=conv.user_id,
                    role='user_preference',content='brighter',metadata_json={'key':'background_brightness','value':'brighter','product_type':product_type,
                        'scenario':scenario,'status':'active','revision':1,'source':'three_approved_cases','evidence_case_ids':[c['id'] for c in cases],
                        'updated_at':datetime.now(timezone.utc).isoformat()},created_at=datetime.now(timezone.utc)))
    return mid


def prompt_rules(memory,current_request=''):
    result=[]
    for p in memory.get('preferences',[]):
        if p['key']=='background_brightness':
            if re.search(r'这次.*(?:不.*提亮|原.*曝光|保持.*光线|暗一点|明亮|更亮|低调|曝光)',current_request):continue
            value={'brighter':'适当提亮背景与环境曝光，不修改服装真实颜色、图案、Logo和号码。','darker':'背景采用较暗氛围，服装商品仍清晰且真实配色不变。','neutral':'背景使用中性曝光，不更改商品事实。'}[p['value']]
        elif p['key'] in ('visual_style','composition'):value=p['value']
        else:continue
        result.append({'id':p['id'],'revision':p['revision'],'instruction':value})
    return result

"""Bounded real HTTP acceptance. All costs pass through the persistent 50-call guard.

Fixed request IDs make rerunning this verifier a read/reconcile operation for
accepted turns. Unknown upstream outcomes are recorded, never retried here.
"""
import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter

import httpx

STATE=Path(__file__).resolve().parent/'.state'
TERMINAL={'completed','succeeded','failed','remote_unknown','blocked','needs_input','awaiting_clarification','awaiting_review','awaiting_confirmation','cancelled'}


async def login(client):
    cfg=json.loads((STATE/'runtime.json').read_text(encoding='utf-8'))
    result=await client.post('/api/v1/auth/login',json={'account':cfg['BOOTSTRAP_ADMIN_ACCOUNT'],'password':cfg['BOOTSTRAP_ADMIN_PASSWORD']})
    result.raise_for_status();client.headers['Authorization']='Bearer '+result.json()['access_token']


async def turn(client,name,text,*,session,controller='dsh',mode='auto',selection=None,**extras):
    request='dsh-live-v1-'+name
    path=STATE/(name+'.json')
    started=perf_counter()
    response=await client.post('/api/v1/experiment/messages',json={'session':session,'request':request,'text':text,'controller':controller,'mode':mode,'selection':selection or {},**extras})
    if not response.is_success:
        value={'http_status':response.status_code,'body':response.text[:1500]};path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');raise RuntimeError(value)
    result=response.json();ack=perf_counter()-started
    reused=bool(result.get('run',{}).get('jobs')) and result.get('state') in TERMINAL and all(j.get('status') in {'succeeded','failed','cancelled'} for j in result['run']['jobs'])
    history=[{'seconds':ack,'state':result.get('state')}]
    for _ in range(200):
        if result.get('state') in TERMINAL or result.get('route') in {'clarify','stopped','status'}:break
        await asyncio.sleep(1.5)
        try:response=await client.get('/api/v1/experiment/turns/'+request,params={'session':session})
        except httpx.TransportError:continue  # Controller restart: read the same durable turn.
        if response.status_code>=500:continue
        response.raise_for_status();result=response.json()
        if history[-1]['state']!=result.get('state'):history.append({'seconds':perf_counter()-started,'state':result.get('state')})
    report={'controller':controller,'text':text,'ack_seconds':ack,'completion_seconds':perf_counter()-started,'replayed_measurement':reused,'history':history,'result':result}
    target=path.with_name(path.stem+'-replay.json') if reused and path.exists() else path
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,result.get('state',result.get('route')),'outputs',len(result.get('run',{}).get('outputs',[])),flush=True)
    return report


async def smoke(client):
    initial=json.loads((STATE/'image-dsh-result.json').read_text(encoding='utf-8'))
    output=initial['run']['outputs'][0]
    # Two independent task executors and original Workers overlap.
    edited,baseline=await asyncio.gather(
        turn(client,'cup-followup','把刚才这张杯子的背景改成浅蓝色，杯子颜色、形状和光线保持不变，只修改这一张，直接生成。',
             session='live-image-dsh',selection={'parent_output_id':output['id']}),
        turn(client,'langgraph-baseline','生成一张纯白色背景上的红色无标识陶瓷杯商品摄影图，45度角，柔和棚拍灯光，不要文字，只需一张，直接生成。',
             session='live-image-baseline',controller='langgraph',mode='task',new_task=True))
    research=await turn(client,'asin-research','调研美国站B0716YP6VJ，只查基础详情，给出商品事实待确认清单，先不要生成图片，也不要查评论或关键词。',
        session='live-amazon',mode='task',new_task=True,selection={'creative_module':'amazon_aplus','review_before_generation':True})
    return {'edited':edited,'baseline':baseline,'research':research}


async def aplus(client):
    first=json.loads((STATE/'image-dsh-result.json').read_text(encoding='utf-8'))
    reference=first['run']['outputs'][0]
    research=json.loads((STATE/'asin-research.json').read_text(encoding='utf-8'))['result']
    facts={'source':'synthetic_test_fixture','appearance':'红色、无标识、杯子外形以参考图为准','material':'陶瓷，仅作为本地测试输入','unknown':['尺寸','容量','认证','耐温性能','品牌']}
    # New creative work is a new Mandate. The earlier research Ticket remains intact.
    plan=await turn(client,'aplus-plan-scoped','上面的ASIN是接口测试样本，不适合作为我方杯子竞品，不能引用其事实。这是独立的杯子A+测试任务，本次只做2个模块。测试商品是红色无标识陶瓷杯，未知尺寸、容量、认证和性能。模块1为产品主视觉，模块2为杯口和把手特写，Basic类型。先给方案，等我确认后再生成。',
        session='live-amazon',mode='task',new_task=True,confirmed_facts=facts,asset_ids=[reference['asset_id']],
        selection={'creative_module':'amazon_aplus','review_before_generation':True})
    creative=plan['result']
    if creative.get('run',{}).get('error_code')=='agent.aplus_design_quality':
        statement='红色无标识陶瓷杯。外观以已上传的测试参考图为准。尺寸、容量、认证、耐温和其它性能均未知。'
        plan=await turn(client,'aplus-plan-grounded','继续当前杯子任务，只做2个模块，先给方案不生成。模块1产品主视觉，模块2杯口和把手特写。商品事实确认原文：'+statement+' 证据来源若使用“用户确认引文：”，其后只允许逐字摘录本轮确认原文，不得改写成其它确认；未知属性不要补造。',
            session='live-amazon',mode='continue',ticket=creative['ticket'],confirmed_facts={'statement':statement},selection={'creative_module':'amazon_aplus','review_before_generation':True})
    if plan['result'].get('state')=='awaiting_clarification':
        plan=await turn(client,'aplus-plan-no-asin','没有参考竞品 ASIN，不需要竞品调研。直接使用已确认的红色无标识陶瓷杯事实和原参考图，只做2个模块：产品主视觉、杯口和把手特写。先给方案，不生成。用户确认引文请逐字摘录已确认事实，未知属性一律不补造。',session='live-amazon',mode='continue',ticket=creative['ticket'],selection={'creative_module':'amazon_aplus','review_before_generation':True})
    if plan['result'].get('state') not in {'awaiting_review','awaiting_confirmation'}:return {'plan':plan,'blocked':'No reviewable real plan'}
    generated=await turn(client,'aplus-generate','确认方案，生成这两个模块。',session='live-amazon',mode='continue',ticket=creative['ticket'])
    outputs=generated['result'].get('run',{}).get('outputs',[])
    if len(outputs)<2:return {'plan':plan,'generated':generated,'blocked':'Two real outputs were not produced'}
    changed=await turn(client,'aplus-module-edit','只修改第二个模块：将背景改成明亮的米白色台面，增强杯口和把手的细节光线。第一模块保持不变，不要重新生成第一模块，直接生成第二模块。',
        session='live-amazon',mode='continue',ticket=creative['ticket'])
    return {'plan':plan,'generated':generated,'changed':changed}


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('suite',choices=['smoke','aplus']);args=parser.parse_args()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:18870',timeout=40,trust_env=False) as client:
        await login(client)
        result=await (smoke(client) if args.suite=='smoke' else aplus(client))
        (STATE/('acceptance-'+args.suite+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':asyncio.run(main())

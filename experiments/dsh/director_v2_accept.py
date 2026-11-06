"""One real Seattle suite, stable request ID. Status reads never resubmit a turn."""
import argparse,json
from pathlib import Path
from accept_platform import client,BASE
OUT=Path(__file__).resolve().parent/'.state/director-v2'
REQUEST='''请使用当前 Seattle 商品原图，直接设计并生成美国站完整 Basic A+ 五个模块，总画面不超过8个，其中最多6个新生图画面。商品外观以原图为准；未确认材质、保暖、防水、定制服务和品牌授权，不得使用这些承诺。不重复请求 B0H2DF4KTQ 历史未知付费状态的 MCP；本次没有可用市场样本，明确区分商品事实、价值解释与未验证的消费动机。
请以专业创意总监身份独立决定具体商业创意、购买理由优先级和整套视觉叙事。不要把帽兜、口袋、罗纹和正反面简单拆成五个卖点；多个细节可以支撑同一消费者价值，弱点合并或舍弃。各模块必须有独立的视觉目的、画面主次、主体位置、构图关系、光线、文字层级与相互差异，避免反复居中商品、站立插兜和同一城市背景。需要精确保真的图案、姓名、号码优先复用原图局部与原生排版，其他场景由现有Worker并发生图。不要询问选款、费用或逐张确认，不额外迭代生成。'''

def read():return json.loads((OUT/'case.json').read_text(encoding='utf-8')) if (OUT/'case.json').exists() else {}
def save(v):(OUT/'case.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def main(action):
    OUT.mkdir(parents=True,exist_ok=True);c=client();case=read()
    if action=='start':
        if 'conversation' not in case:
            r=c.post(BASE+'/agent/conversations',json={'context_kind':'chat','title':'Seattle · 创意设计转化 v2 对照'});r.raise_for_status()
            case={'conversation':r.json()['id'],'asset':'2d25d7ad-5183-4411-b238-76dee7abbb29','request':REQUEST};save(case)
        if 'attachment' not in case:
            r=c.post(BASE+'/agent/conversations/'+case['conversation']+'/attachments',json={'asset_id':case['asset']});r.raise_for_status();case['attachment']=r.json()['id'];save(case)
        if 'run' not in case:
            r=c.post(BASE+'/agent/conversations/'+case['conversation']+'/messages',json={'content':REQUEST,'client_request_id':'seattle-director-v2-20261106-one-suite','chat_mode':True,'auto_execute':True,'attachment_ids':[case['attachment']]});r.raise_for_status();case['run']=r.json()['id'];save(case)
    if 'run' not in case:raise SystemExit('No acceptance started; status does not start paid work.')
    if action=='edit' and 'edit_run' not in case:
        original=c.get(BASE+'/agent/runs/'+case['run']);original.raise_for_status()
        hero=next(o for o in original.json()['outputs'] if o['amazon_module']['module_id']=='m1_hero')
        case['edit_request']='只重做当前主视觉这1张，其他7个画面、原生文案和整套主题保持。现图仍是人物加城市背景，没有把创意转成设计。请独立设计一张非人物的商业创意主视觉：以本商品图案的弧线/轮廓关系组织画面，采用编辑式静物或图形化的商品与环境关系，形成明确主次、位置与留白；禁止站立模特、插兜、人物和城市实景天际线。保留原商品的真实渐变、Logo和图案字形，不新增营销文字；不要仅美化原图天空。只生成1张，不自动迭代。'
        r=c.post(BASE+'/agent/conversations/'+case['conversation']+'/messages',json={'content':case['edit_request'],'client_request_id':'seattle-director-v2-hero-once','chat_mode':True,'auto_execute':True,'attachment_ids':[case['attachment']],'parent_output_id':hero['id']});r.raise_for_status()
        case['edit_run']=r.json()['id'];case['hero_parent']=hero['id'];save(case)
    run_id=case['edit_run'] if action in {'edit','edit-status'} else case['run']
    r=c.get(BASE+'/agent/runs/'+run_id);r.raise_for_status();run=r.json();(OUT/('edit-run.json' if action in {'edit','edit-status'} else 'run.json')).write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'conversation':case['conversation'],'run':run['id'],'status':run['status'],'jobs':[{'id':j['id'],'type':j['capability'],'status':j['status'],'error':j.get('error_code')} for j in run['jobs']],'outputs':len(run.get('outputs',[])),'error':run.get('error_code')},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['start','status','edit','edit-status']);main(p.parse_args().action)

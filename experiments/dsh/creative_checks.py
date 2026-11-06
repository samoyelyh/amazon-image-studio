"""Bounded real chat/clarification, exact-output edit and HTTP ownership checks."""
import argparse,json
from creative_accept import OUT,book,save
from accept_platform import client,BASE
PATH=OUT/'checks.json'
def records():return json.loads(PATH.read_text(encoding='utf-8')) if PATH.exists() else {}
def persist(v):PATH.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def start(name,text,*,conversation=None,parent=None,new_task=False):
 c=client();v=records()
 if name not in v:
  if not conversation:
   r=c.post(BASE+'/agent/conversations',json={'context_kind':'chat','title':'创意总监边界验收 · '+name});r.raise_for_status();conversation=r.json()['id']
  v[name]={'conversation':conversation,'text':text};persist(v)
 item=v[name]
 if 'run' not in item:
  payload={'content':text,'client_request_id':'creative-check-'+name,'chat_mode':True,'auto_execute':True}
  if parent:payload['parent_output_id']=parent
  if new_task:payload['start_new_task']=True
  r=c.post(BASE+'/agent/conversations/'+item['conversation']+'/messages',json=payload);r.raise_for_status();item['run']=r.json()['id'];persist(v)
 r=c.get(BASE+'/agent/runs/'+item['run']);r.raise_for_status();result=r.json();item['status']=result['status'];item['image_jobs']=[j['id'] for j in result['jobs'] if j['capability']!='text_generation'];item['outputs']=[o['id'] for o in result['outputs']];persist(v)
 (OUT/('check-'+name+'-latest.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'case':name,**item},ensure_ascii=False));return result
def edit():
 c=client();b=book()['new-mouse'];r=c.get(BASE+'/agent/runs/'+b['run']);r.raise_for_status();result=r.json();outputs=sorted(result['outputs'],key=lambda o:o['number']);target=outputs[0]
 before=OUT/'edit-before.json'
 if not before.exists():before.write_text(json.dumps(outputs,ensure_ascii=False,indent=2),encoding='utf-8')
 return start('edit','只修改已选这张鼠标主视觉：移除桌面右下角的棕色笔记本和钢笔，改为干净冷灰色桌面；鼠标本身、Logo、按钮、滚轮和其他四张附图及原生文案全部保持。只重新生成这一张。',conversation=b['conversation'],parent=target['id'])
def detail():
 c=client();b=book()['new-hoodie'];r=c.get(BASE+'/agent/runs/'+b['run']);r.raise_for_status();result=r.json()
 target=next(o for o in result['outputs'] if o['amazon_module'].get('slot_id')=='block2')
 before=OUT/'detail-before.json'
 if not before.exists():before.write_text(json.dumps(result['outputs'],ensure_ascii=False,indent=2),encoding='utf-8')
 return start('detail','只修改已选的渐变配色细节图：画面只保留真实藏青到青绿过渡区域的紧凑近景，以颜色过渡和可见表面为焦点。不要整件卫衣，不要圆形放大镜、气泡、拼图或第二个视角，不虚构微观纤维。只生成这一个槽位，其他七张图片、所有文案和商品图案均保持。',conversation=b['conversation'],parent=target['id'])
def isolate():
 a=client();other=client(1);result={}
 for name,item in book().items():
  if not name.startswith('new-'):continue
  r=a.get(BASE+'/agent/runs/'+item['run']);r.raise_for_status();run=r.json()
  paths={'conversation':'/agent/conversations/'+item['conversation'],'run':'/agent/runs/'+item['run']}
  if run['outputs']:
   paths['output']=run['outputs'][0]['content_url'].removeprefix('/api/v1')
   pid=run['outputs'][0]['amazon_module']['plan_id'];paths['archive']='/agent/conversations/'+item['conversation']+'/amazon-plans/'+pid+'/archive'
  result[name]={}
  for k,p in paths.items():
   r=other.get(BASE+p);assert r.status_code in {403,404},(k,r.status_code);result[name][k]=r.status_code
 r=other.put(BASE+'/agent/controller',json={'controller':'langgraph'});assert r.status_code==403;result['member_switch_denied']=r.status_code
 v=records();v['isolation']=result;persist(v);print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action');a=p.parse_args()
 if a.action=='chat':start('chat','你好，请简短说明你如何根据不同商品策划营销图片，只回答问题，不创建任何图片任务。')
 elif a.action=='clarify':start('clarify','帮我做一套图')
 elif a.action=='edit':edit()
 elif a.action=='detail':detail()
 elif a.action=='plan-only':start('plan-only','我想先审阅一套新的美国站三张Listing附图方案。沿用本对话里MX Anywhere 3S的官方事实和素材，五点购买理由可以合并映射到三张。只保存策划，不生成任何图片。',conversation=book()['new-mouse']['conversation'],new_task=True)
 elif a.action=='isolate':isolate()
 elif a.action=='status':
  for name,v in records().items():
   if 'run' in v:start(name,v['text'])

"""Owned real outputs, full-suite contact comparisons and sanitized decision evidence."""
import json,sqlite3,statistics,io,hashlib
from pathlib import Path
from zipfile import ZipFile
from PIL import Image,ImageDraw,ImageFont,ImageOps
from creative_accept import OUT,book,PRODUCTS
from accept_platform import client,BASE,STATE,records
ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/dsh/evidence/creative';DEST.mkdir(parents=True,exist_ok=True)
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def connection(name):c=sqlite3.connect(STATE/'runtime'/name);c.row_factory=sqlite3.Row;return c
def collect():
 c=client();cases=book();cases['old-hoodie']=records()['aplus'];report={'cases':{},'sources':{k:{a:b for a,b in v.items() if a in {'source','facts','images','local'}} for k,v in PRODUCTS.items()}}
 core=connection('core/native-control.sqlite');gateway=connection('native-gateway.sqlite');ledger=connection('worker/budget.sqlite')
 for name,item in cases.items():
  r=c.get(BASE+'/agent/runs/'+item['run']);r.raise_for_status();run=r.json();dump(OUT/(name+'-latest.json'),run)
  conv=c.get(BASE+'/agent/conversations/'+item['conversation']);conv.raise_for_status();conv=conv.json()
  plans=conv.get('amazon_plans',[])
  turn=run['result']['dsh_turn'];native=json.loads(core.execute('select result from requests where id=?',(turn,)).fetchone()[0])
  pid=next((o.get('amazon_module',{}).get('plan_id') for o in run['outputs']),None)
  plan=next((p for p in plans if p['id']==pid),plans[0] if plans else None)
  calls=[]
  for row in ledger.execute('select * from calls where id in ('+','.join('?' for _ in run['jobs'])+')',[j['id'] for j in run['jobs']]) if run['jobs'] else []:
   d=json.loads(row['details']);role=gateway.execute('select role from model_jobs where job=?',(row['id'],)).fetchone()
   calls.append({'job':row['id'],'kind':row['kind'],'model':row['model'],'role':role[0] if role else None,'state':row['state'],'seconds':round(row['finished']-row['started'],3) if row['finished'] else None,'usage':d.get('usage'),'api_cost':d.get('api_cost'),'started':row['started'],'finished':row['finished']})
  evidence={'conversation':item['conversation'],'run':item['run'],'development_runs':item.get('development_runs',[]),'ticket':run['result'].get('dsh_ticket'),'status':run['status'],
   'planning_seconds':native.get('seconds'),'recovery_count':native.get('recovery_count',0),'main_calls':native.get('main_calls'),'executor_calls':native.get('executor_calls'),'quality':native.get('quality'),
   'sessions':run['result'].get('native_sessions'),'plan':plan,'outputs':run['outputs'],'prompts':run['prompts'],'calls':calls,
   'events':[e for e in native.get('events',[]) if e['type'] in {'main.decision','skill.bound','tool.start','tool.result','tool.error','quality.review'}]}
  evidence['display_outputs']=[o for v in conv.get('runs',[]) for o in v.get('outputs',[])] or run['outputs']
  evidence['display_outputs']=[o for o in evidence['display_outputs'] if o.get('amazon_module',{}).get('plan_id')==pid] if pid else run['outputs']
  report['cases'][name]=evidence
  directory=OUT/'delivery'/name;directory.mkdir(parents=True,exist_ok=True)
  for o in evidence['display_outputs']:
   path=directory/(o['id']+'.png')
   if not path.exists():
    r=c.get('http://127.0.0.1:18080'+o['content_url']);r.raise_for_status();path.write_bytes(r.content)
   Image.open(path).verify()
  if plan and run['outputs'] and all(j['status']=='succeeded' for j in run['jobs'] if j['capability']!='text_generation'):
   archive=directory/'suite.zip'
   revision_file=directory/'archive-revision.txt'
   if not archive.exists() or not revision_file.exists() or revision_file.read_text()!=str(plan['revision']):
    r=c.get(BASE+'/agent/conversations/'+item['conversation']+'/amazon-plans/'+plan['id']+'/archive',timeout=90);r.raise_for_status();archive.write_bytes(r.content);revision_file.write_text(str(plan['revision']))
   with ZipFile(archive) as z:
    assert not z.testzip()
    for entry in z.infolist():
     target=(directory/'native-preview'/entry.filename).resolve()
     assert target.is_relative_to((directory/'native-preview').resolve())
     if not entry.is_dir():target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(entry))
  dump(DEST/(name+'.json'),evidence)
 window=[dict(r) for r in ledger.execute("select c.* from calls c join call_windows w on w.id=c.id where w.window='creative-director-20261106'")]
 report['window_calls']={kind:sum(v['kind']==kind for v in window) for kind in ['text','image','mcp']}
 report['calls']=[]
 for row in window:
  d=json.loads(row['details']);role=gateway.execute('select role from model_jobs where job=?',(row['id'],)).fetchone()
  report['calls'].append({'job':row['id'],'kind':row['kind'],'model':row['model'],'role':role[0] if role else None,'state':row['state'],
   'seconds':round(row['finished']-row['started'],3) if row['finished'] else None,'usage':d.get('usage'),'api_cost':d.get('api_cost'),'started':row['started'],'finished':row['finished']})
 report['planning_means']={g:round(statistics.mean(report['cases'][g+'-'+p]['planning_seconds'] for p in PRODUCTS),3) for g in ['old','new']}
 activity=sorted([(v['started'],1) for v in window if v['kind']=='image']+[(v['finished'],-1) for v in window if v['kind']=='image' and v['finished']]);active=peak=0
 for _,delta in activity:active+=delta;peak=max(peak,active)
 report['peak_image_concurrency']=peak
 checks=OUT/'checks.json'
 report['checks']=json.loads(checks.read_text(encoding='utf-8')) if checks.exists() else {}
 report['cost_note']='Currency cost unknown unless returned by provider. Actual token usage retained when supplied. Development correction/recovery calls are included.'
 index={**report,'cases':{n:{**{k:x for k,x in v.items() if k not in {'plan','events','outputs','prompts','display_outputs','calls'}},
  'evidence_file':n+'.json','output_count':len(v['outputs']),'output_ids':[o['id'] for o in v['outputs']]} for n,v in report['cases'].items()}}
 dump(DEST/'measurements.json',index)
 for product in PRODUCTS:
  if 'old-'+product in report['cases'] and 'new-'+product in report['cases']:comparison(product,report['cases']['old-'+product],report['cases']['new-'+product])
 print(json.dumps({'status':{k:v['status'] for k,v in report['cases'].items()},'calls':report['window_calls']},ensure_ascii=False))
 return report
FONT='C:/Windows/Fonts/msyh.ttc'
def text_lines(text,font,width):
 lines=[]
 for paragraph in str(text).splitlines():
  line=''
  for ch in paragraph:
   if font.getlength(line+ch)>width:lines.append(line);line=ch
   else:line+=ch
  lines.append(line)
 return lines
def column(name,data):
 width=650;small=ImageFont.truetype(FONT,18);heading=ImageFont.truetype(FONT,24);parts=[]
 def label(text,font=small):
  lines=text_lines(text,font,width-36);im=Image.new('RGB',(width,max(1,len(lines))*28+24),'#f5f4ef');d=ImageDraw.Draw(im)
  for i,line in enumerate(lines):d.text((18,12+i*28),line,font=font,fill='#202020')
  parts.append(im)
 label(name+' · 完整画面与原生文案拼接',heading)
 if not data.get('plan'):label('方案未完成');return parts[0]
 strategy=data['plan']['plan'].get('creative_strategy')
 if strategy:label('创意主题：'+strategy['concept']['theme'])
 modules=data['plan']['plan']['modules'];outputs=data.get('display_outputs') or data['outputs'];used=set()
 for i,m in enumerate(modules,1):
  label(f'{i}. '+m['title'],heading)
  found=[o for o in outputs if o.get('amazon_module',{}).get('module_id')==m['id']]
  latest={}
  for o in found:
   slot=o['amazon_module'].get('slot_id','main')
   if slot not in latest or o['version']>latest[slot]['version']:latest[slot]=o
  for o in latest.values():
   path=OUT/'delivery'/name/(o['id']+'.png')
   with Image.open(path) as raw:
    image=raw.convert('RGB');image=ImageOps.contain(image,(width,1300));parts.append(image)
   used.add(o['id']);label(o['amazon_module'].get('slot_id','main')+f' · {o["width"]}×{o["height"]} · '+o['id'][:8])
  label(m['headline']+'\n'+m['body'])
 height=sum(p.height for p in parts);canvas=Image.new('RGB',(width,height),'white');y=0
 for part in parts:canvas.paste(part,((width-part.width)//2,y));y+=part.height
 return canvas
def comparison(product,old,new):
 left=column('old-'+product,old);right=column('new-'+product,new)
 result=Image.new('RGB',(1320,max(left.height,right.height)),'#e4e3de');result.paste(left,(0,0));result.paste(right,(670,0));result.save(DEST/(product+'-full-comparison.jpg'),quality=90)
if __name__=='__main__':collect()

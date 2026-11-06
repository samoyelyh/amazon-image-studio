"""Read-only local acceptance artifacts and sanitized real-call measurements."""
import json,sqlite3,statistics,hashlib,shutil
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
from accept_platform import client,records,BASE,STATE
ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/dsh/evidence/platform'
DEST.mkdir(parents=True,exist_ok=True)
c=client();cases=records();measurements={}
gateway=sqlite3.connect(STATE/'runtime/native-gateway.sqlite');gateway.row_factory=sqlite3.Row
core=sqlite3.connect(STATE/'runtime/core/native-control.sqlite')
ledger=sqlite3.connect(STATE/'runtime/worker/budget.sqlite');ledger.row_factory=sqlite3.Row
report={'default_controller':c.get(BASE+'/agent/status').json()['controller'],'cases':{},'calls':[]}
for name,item in cases.items():
    r=c.get(BASE+'/agent/runs/'+item['run']);r.raise_for_status();v=r.json()
    turn=v['result']['dsh_turn'];native=json.loads(core.execute('SELECT result FROM requests WHERE id=?',(turn,)).fetchone()[0])
    decisions=[e for e in native.get('events',[]) if e['type'] in ['main.decision','skill.bound','tool.result','engine.assignment']]
    report['cases'][name]={'conversation':item['conversation'],'run':item['run'],'status':v['status'],'ticket':v['result'].get('dsh_ticket'),
        'planning_seconds':native.get('seconds'),'main_seconds':native.get('main_seconds'),'recovery_count':native.get('recovery_count',0),'executor_calls':native.get('executor_calls'),
        'sessions':v['result'].get('native_sessions'),'events':[{'type':e['type'],'tool':e.get('name'),'id':e.get('id'),'content_hash':e.get('content_hash')} for e in decisions],
        'jobs':v['jobs'],'outputs':[{k:o[k] for k in ['id','asset_id','job_id','number','version','width','height','parent_output_id','root_output_id']} for o in v['outputs']]}
    if name in {'aplus','edit','listing'}:
        directory=STATE/'delivery'/name;directory.mkdir(parents=True,exist_ok=True)
        for o in v['outputs']:
            path=directory/(str(o['number'])+'-v'+str(o['version'])+'.png')
            response=c.get('http://127.0.0.1:18080'+o['content_url']);response.raise_for_status();path.write_bytes(response.content)
            Image.open(path).verify()
for row in ledger.execute('SELECT * FROM calls ORDER BY started'):
    details=json.loads(row['details']);role=gateway.execute('SELECT role FROM model_jobs WHERE job=?',(row['id'],)).fetchone()
    report['calls'].append({'job':row['id'],'kind':row['kind'],'role':role[0] if role else None,'model':row['model'],'status':row['state'],'seconds':round(row['finished']-row['started'],3),
        'started':row['started'],'finished':row['finished'],'usage':details.get('usage'),'api_cost':details.get('api_cost'),'transport':details.get('transport')})
report['paid_call_counts']={kind:sum(v['kind']==kind for v in report['calls']) for kind in ['text','image','mcp']}
report['planning_mean_seconds']=statistics.mean(report['cases'][name]['planning_seconds'] for name in ['aplus','listing','edit'])
report['main_model_mean_seconds']=statistics.mean(v['seconds'] for v in report['calls'] if v['role']=='main')
report['recovery_external_requests']=0
report['api_cost_note']='No provider currency amount returned; missing usage is unknown, never zero.'
for name in ['isolation','edit-acceptance','rollback-acceptance']:
    report[name]=json.loads((STATE/(name+'.json')).read_text(encoding='utf-8'))
events=sorted([(v['started'],1) for v in report['calls'] if v['kind']=='image']+[(v['finished'],-1) for v in report['calls'] if v['kind']=='image']);active=peak=0
for _,delta in events:active+=delta;peak=max(peak,active)
report['image_peak_concurrency']=peak
(DEST/'measurements.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',18)
for name in ['aplus','listing','edit']:
    paths=sorted((STATE/'delivery'/name).glob('*.png'),key=lambda p:int(p.stem.split('-')[0]));cols=3 if len(paths)>3 else len(paths);rows=(len(paths)+cols-1)//cols
    sheet=Image.new('RGB',(cols*420,rows*350),'#f3f3f0');draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(paths):
        with Image.open(p) as im:
            thumb=ImageOps.contain(im.convert('RGB'),(406,308));x=(i%cols)*420+(420-thumb.width)//2;y=(i//cols)*350+28+(308-thumb.height)//2;sheet.paste(thumb,(x,y))
            draw.text(((i%cols)*420+12,(i//cols)*350+5),p.stem+'  '+str(im.width)+'×'+str(im.height),font=font,fill='#222222')
    sheet.save(DEST/(name+'-contact.jpg'),quality=88)
source=Path(r'C:\Users\Woda\Downloads\aplus-c69290eb-b4f5-483f-b6e4-72ebc1e72f6e.zip')
if source.exists():shutil.copy2(source,STATE/'delivery/Seattle-Aplus-18080.zip')
print(json.dumps({'controller':report['default_controller'],'paid_calls':report['paid_call_counts'],'planning_mean_seconds':round(report['planning_mean_seconds'],3),'main_mean_seconds':round(report['main_model_mean_seconds'],3),'image_peak_concurrency':peak,'outputs':{name:len(report['cases'][name]['outputs']) for name in ['aplus','listing','edit']}},ensure_ascii=False))

"""Bounded real Kimi Main-router benchmark; tools are described, never executed."""
import argparse,asyncio,hashlib,json,re,sys,time
from pathlib import Path
import httpx
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'server'))
from app.experiments.dsh.ledger import Ledger

SCHEMA={'type':'object','properties':{
    'action':{'type':'string','enum':['chat','clarify','task','continue','status','stop']},
    'message':{'type':'string'},'executor':{'type':'string','enum':['amazon_aplus','listing','research','image_edit','batch_images','none']},
    'ticket':{'type':['string','null']}},'required':['action','message','executor','ticket'],'additionalProperties':False}
CASES=[('chat','A+和Listing图片有什么区别？','chat'),('clarify','帮我做一套图','clarify'),
    ('aplus','使用已上传的商品图，为美国站制作整套Basic A+并直接生成。未知材质、性能和定制服务不写。','task')]

def prompt():
    source=(ROOT/'experiments/dsh/native-controller.mjs').read_text(encoding='utf-8')
    match=re.search(r'const mainPrompt=`(.*?)`;',source,re.S)
    if not match:raise RuntimeError('Cannot locate the actual DSH Main system prompt')
    return match.group(1)

def system_proxy():
    if sys.platform!='win32':return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as k:
            enabled=winreg.QueryValueEx(k,'ProxyEnable')[0];server=winreg.QueryValueEx(k,'ProxyServer')[0]
        if enabled and re.fullmatch(r'127\.0\.0\.1:\d+',server):return 'http://'+server
    except OSError:pass
    return None

async def request(client,key,model,body):
    started=time.perf_counter();result={'requested_model':model,'stream':True};calls={};text=[];reasoning_chars=0;usage=None;done=False;finish=None
    async with client.stream('POST','https://api.kimi.com/coding/v1/chat/completions',headers={'Authorization':'Bearer '+key},json=body) as r:
        result.update(http_status=r.status_code,headers_seconds=round(time.perf_counter()-started,4))
        if r.status_code>=400:
            raw=(await r.aread()).decode(errors='replace').replace(key,'[redacted]')
            result['error']=re.sub(r'sk-kimi-[A-Za-z0-9_-]+','[redacted]',raw)[:600]
            result['seconds']=round(time.perf_counter()-started,4);return result
        result['content_type']=r.headers.get('content-type','')
        async for line in r.aiter_lines():
            if not line.startswith('data:'):continue
            raw=line[5:].strip()
            if raw=='[DONE]':done=True;break
            data=json.loads(raw);now=round(time.perf_counter()-started,4)
            result.setdefault('first_event_seconds',now)
            if data.get('model'):result['reported_model']=data['model']
            if data.get('usage'):usage=data['usage']
            for choice in data.get('choices') or []:
                if choice.get('index',0)!=0:continue
                if choice.get('finish_reason'):finish=choice['finish_reason']
                delta=choice.get('delta') or {}
                reasoning=delta.get('reasoning_content') or ''
                if reasoning:result.setdefault('first_reasoning_seconds',now);reasoning_chars+=len(reasoning)
                if delta.get('content'):
                    result.setdefault('first_decision_delta_seconds',now);text.append(delta['content'])
                for item in delta.get('tool_calls') or []:
                    result.setdefault('first_decision_delta_seconds',now)
                    c=calls.setdefault(item.get('index',0),{'id':'','name':'','arguments':''})
                    if item.get('id'):c['id']+=item['id']
                    fn=item.get('function') or {};c['name']+=fn.get('name') or '';c['arguments']+=fn.get('arguments') or ''
    result.update(seconds=round(time.perf_counter()-started,4),usage=usage,finish_reason=finish,complete=done or finish is not None,reasoning_characters=reasoning_chars,text=''.join(text),tool_calls=list(calls.values()))
    return result

async def main(args):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',args.run_id):raise ValueError('Invalid run ID')
    if args.ceiling<50 or args.ceiling>56:raise ValueError('This benchmark permits only the authorized cumulative ceiling 50..56')
    if args.key_stdin:
        import getpass
        if not sys.stdin.isatty():raise RuntimeError('Interactive no-echo input requires a terminal')
        key=getpass.getpass('Kimi benchmark key (not saved): ').strip()
    else:key=__import__('os').environ.get('KIMI_API_KEY','').strip()
    if not key:raise RuntimeError('Kimi Code API key is missing')
    state=ROOT/'experiments/dsh/.state';ledger=Ledger(state/'worker',limit=args.ceiling)
    folder=state/'kimi-benchmark';folder.mkdir(exist_ok=True);output=folder/(args.run_id+'.json')
    instructions=prompt();fingerprint=hashlib.sha256(json.dumps([args.model,instructions,SCHEMA,CASES],ensure_ascii=False).encode()).hexdigest()
    if output.exists():
        old=json.loads(output.read_text());assert old['fingerprint']==fingerprint,'Run ID is immutable; changed inputs require an explicit new run'
        report=old
    else:report={'run_id':args.run_id,'model':args.model,'effort':'low','fingerprint':fingerprint,'main_prompt_sha256':hashlib.sha256(instructions.encode()).hexdigest(),'tools_executed':0,'max_requests':3,'results':[]}
    proxy=system_proxy();report['system_loopback_proxy']=proxy is not None
    def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    async with httpx.AsyncClient(timeout=httpx.Timeout(90,connect=15),trust_env=False,proxy=proxy) as client:
        for name,question,expected in CASES:
            id='kimi-main:'+args.run_id+':'+name
            cached=ledger.reserve(id,'text','kimi:'+args.model)
            if cached is not None:
                print(name,'cached',flush=True);continue
            value={'request':question,'mode':'auto','selected_ticket':None,'force_new_task':name=='aplus','asset_ids':['product-reference-1'] if name=='aplus' else [],'selection':{},'tickets':[]}
            body={'model':args.model,'reasoning_effort':'low','max_tokens':1200,'stream':True,'stream_options':{'include_usage':True},
                'messages':[{'role':'system','content':instructions},{'role':'user','content':json.dumps(value,ensure_ascii=False)}],
                'tools':[{'type':'function','function':{'name':'route_task','description':'Answer, clarify, or dispatch an authorized platform task.','parameters':SCHEMA}}]}
            print('START',name,args.model,flush=True)
            try:
                result=await request(client,key,args.model,body);result['case']=name;result['expected']=expected
                decisions=[]
                for call in result.get('tool_calls',[]):
                    if call['name']!='route_task':raise ValueError('Unexpected tool')
                    decision=json.loads(call['arguments']);Draft202012Validator(SCHEMA).validate(decision);decisions.append(decision)
                result['decisions']=decisions
                result['correct']=len(decisions)==1 and decisions[0]['action']==expected and (name!='aplus' or decisions[0]['executor']=='amazon_aplus')
                report['results'].append(result);save()
                ledger.finish(id,'succeeded' if result.get('complete') and result.get('http_status')==200 else 'failed_or_unknown',{'usage':result.get('usage'),'transport':{k:result.get(k) for k in ['http_status','headers_seconds','first_event_seconds','first_decision_delta_seconds','seconds']},'api_cost':None,'benchmark_file':str(output)})
                print('DONE',name,result.get('http_status'),result.get('seconds'),'correct',result['correct'],flush=True)
                if result.get('http_status') in {400,401,403,429}:break
            except Exception as error:
                ledger.finish(id,'failed_or_unknown',{'code':type(error).__name__,'api_cost':None})
                report['results'].append({'case':name,'error':type(error).__name__,'outcome':'unknown','automatic_retry':False});save();raise
    print('REPORT',output,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',choices=['kimi-for-coding','k3.1-pro','k3.1-pro-highspeed'],default='kimi-for-coding');p.add_argument('--run-id',required=True);p.add_argument('--ceiling',type=int,default=50);p.add_argument('--key-stdin',action='store_true');asyncio.run(main(p.parse_args()))

"""Bounded real 18080 acceptance. Stable request IDs; never resends unknown work."""
import argparse,json,time,asyncio,sqlite3
from pathlib import Path
import httpx
STATE=Path(__file__).resolve().parent/'.state/deployment'
BASE='http://127.0.0.1:18080/api/v1'
def client(index=0):
    login=json.loads((STATE/'login.json').read_text(encoding='utf-8'))[index]
    c=httpx.Client(timeout=45,trust_env=False)
    data={k:login[k] for k in ['account','password']}
    gateway=STATE/'runtime/native-gateway.sqlite'
    if gateway.exists():
        with sqlite3.connect(gateway) as db:row=db.execute('SELECT owner FROM turns ORDER BY created LIMIT 1').fetchone()
        if row:data['organization_id']=json.loads(row[0])['org']
    r=c.post(BASE+'/auth/login',json=data);r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token'];return c
def records():return json.loads((STATE/'cases.json').read_text()) if (STATE/'cases.json').exists() else {}
def save(cases): (STATE/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
def case(name,text,attachments=None,parent=None):
    c=client();data=records()
    if name not in data:
        r=c.post(BASE+'/agent/conversations',json={'context_kind':'chat','title':'DSH 正式验收 · '+name});r.raise_for_status();data[name]={'conversation':r.json()['id']};save(data)
    item=data[name]
    if 'run' not in item:
        r=c.post(BASE+'/agent/conversations/'+item['conversation']+'/messages',json={'content':text,'client_request_id':'dsh-deploy-'+name+'-v1','chat_mode':True,'auto_execute':True,'attachment_ids':attachments or [],'parent_output_id':parent})
        r.raise_for_status();item['run']=r.json()['id'];save(data)
    r=c.get(BASE+'/agent/runs/'+item['run']);r.raise_for_status();value=r.json()
    (STATE/(name+'-latest.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'case':name,'conversation':item['conversation'],'run':item['run'],'status':value['status'],'jobs':[(j['capability'],j['status']) for j in value['jobs']],'error':value.get('error_code')},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',choices=['chat','clarify','status']);a=p.parse_args()
    if a.case=='status':
        for name,item in records().items():case(name,'unused')
    else:case(a.case,'你好，请用一句话介绍你能帮我做什么，不生成图片。' if a.case=='chat' else '帮我做一套图')

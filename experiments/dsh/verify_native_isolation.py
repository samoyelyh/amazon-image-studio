"""Zero-provider HTTP isolation checks against native DSH and original assets."""
import asyncio,json
from pathlib import Path
import httpx
from verify_isolation import seed,STATE
from verify_native import client

async def main():
    accounts=await seed();admin=await client()
    a=json.loads((STATE/'native-product-assets.json').read_text(encoding='utf-8'))
    original=await admin.get('/api/v1/experiment/native/turns/native-real-aplus-v2',params={'session':'native-product-v2'})
    original.raise_for_status();ticket=original.json()['ticket'];results=[]
    output=original.json()['run']['outputs'][0];conv=original.json()['conversation'];plan=output['amazon_module']['plan_id']
    for account,password in accounts:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:18870',trust_env=False,timeout=20) as c:
            r=await c.post('/api/v1/auth/login',json={'account':account,'password':password});r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token']
            checks={}
            for name,url in [('native_turn','/api/v1/experiment/native/turns/native-real-aplus-v2?session=native-product-v2'),('asset','/api/v1/assets/'+a[0]['id']+'/content'),
                ('output','/api/v1/assets/'+output['asset_id']+'/download'),('zip','/api/v1/agent/conversations/'+conv+'/amazon-plans/'+plan+'/archive')]:
                response=await c.get(url);checks[name]=response.status_code;print(account,name,response.status_code,response.text[:150],flush=True);assert response.status_code in {403,404}
            response=await c.post('/api/v1/experiment/messages',json={'session':'foreign-denied','request':'foreign-'+account,'text':'继续这个任务','ticket':ticket})
            checks['foreign_ticket']=response.status_code;assert response.status_code in {403,404}
            response=await c.post('/api/v1/experiment/messages',json={'session':'foreign-denied','request':'foreign-asset-'+account,'text':'生成A+','asset_ids':[a[0]['id']]})
            checks['foreign_asset']=response.status_code;assert response.status_code in {403,404}
            results.append({'account':account,'checks':checks})
    await admin.aclose()
    report={'passed':True,'provider_calls':0,'checks':results}
    (STATE/'native-isolation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())

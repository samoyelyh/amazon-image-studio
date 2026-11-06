"""Bounded real-provider acceptance runner. Each request has a fixed identity."""
import argparse,asyncio,json,sqlite3
from pathlib import Path
from time import perf_counter
import httpx
STATE=Path(__file__).resolve().parent/'.state'

async def client():
    c=httpx.AsyncClient(base_url='http://127.0.0.1:18870',timeout=40,trust_env=False)
    cfg=json.loads((STATE/'runtime.json').read_text(encoding='utf-8'))
    r=await c.post('/api/v1/auth/login',json={'account':cfg['BOOTSTRAP_ADMIN_ACCOUNT'],'password':cfg['BOOTSTRAP_ADMIN_PASSWORD']})
    r.raise_for_status();c.headers['Authorization']='Bearer '+r.json()['access_token'];return c

async def assets(c):
    path=STATE/'native-product-assets.json'
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    product=Path(r'C:\Users\Woda\Desktop\11.4\主图');templates=Path(r'C:\Users\Woda\Desktop\11.4\模板')
    files=list(product.glob('*.png'));files.sort(key=lambda p:(p.stem!='Seattle',p.name))
    result=[]
    for p in files+list(templates.glob('*.png')):
        r=await c.post('/api/v1/assets',files={'file':(p.name,p.read_bytes(),'image/png')},data={'category':'product_reference'})
        r.raise_for_status();a=r.json();result.append({'id':a['id'],'name':p.name,'source':str(p),'role':'product' if p.parent==product else 'design_reference'})
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result

async def submit(c,name,text,**kwargs):
    start=perf_counter();r=await c.post('/api/v1/experiment/messages',json={'session':'native-product-suite','request':name,'text':text,'controller':'dsh',**kwargs})
    r.raise_for_status();result=r.json();print(name,result['state'],'ack',round(perf_counter()-start,3),flush=True)
    (STATE/(name+'-ack.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result

async def read(c,name,session='native-product-suite'):
    r=await c.get('/api/v1/experiment/turns/'+name,params={'session':session});r.raise_for_status();result=r.json()
    (STATE/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,result['state'],'answer',result.get('answer','')[:200],'outputs',len(result.get('run',{}).get('outputs',[])),flush=True)
    if result.get('native',{}).get('error'):print(result['native']['error'])
    return result

async def main(args):
    c=await client()
    try:
        if args.command=='aplus':
            a=await assets(c)
            await submit(c,'native-real-aplus-v1','请使用我上传的真实商品主图和设计参考，为商品做完整专业Amazon A+并自动生成整套图片。你自行选一款城市商品和适用站点，其他城市图只是款式备选，模板只借鉴设计。竞品ASIN B0H2DF4KTQ，请按需通过真实卖家精灵MCP研究。商品材质、性能和定制服务未知，不写这些承诺，保留原图Logo、图案、字样、颜色和背面姓名号码原样。整套需不同模块布局和尺寸，不能是重复横幅或拼图。',
                asset_ids=[v['id'] for v in a],new_task=True)
        elif args.command=='read':await read(c,args.request,args.session)
        elif args.command=='edit':
            original=await read(c,'native-real-aplus-v1')
            await submit(c,'native-real-edit-v1','只修改原方案第三个模块的图片：改成室内更衣室的商业摄影场景，保留商品身份、图案和整体品牌风格，其他模块和输出保持原样。直接生成修改结果。',ticket=original['ticket'])
    finally:await c.aclose()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['aplus','read','edit']);p.add_argument('--request',default='native-real-aplus-v1');p.add_argument('--session',default='native-product-suite');asyncio.run(main(p.parse_args()))

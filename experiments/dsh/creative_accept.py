"""Real three-category acceptance through the deployed UI API; stable IDs, no retries."""
import argparse,json,time,hashlib
from pathlib import Path
import httpx
from accept_platform import client,BASE,STATE
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'experiments/dsh/.state/creative';OUT.mkdir(exist_ok=True,parents=True)
PRODUCTS={
 'mug':{'source':'https://www.ikea.com/us/en/p/faergklar-mug-matte-green-40478189/','deliverable':'A+ Basic 五个模块，完整覆盖每个模块的独立图片槽位',
 'facts':'IKEA FÄRGKLAR 杯子，matte green，产品号404.781.89；石器（Stoneware），彩色釉（Colored glaze）；可微波炉使用（Microwave-safe），可洗碗机清洗（Dishwasher-safe）；官方标称容量13 oz、高4英寸。不得声称保温、防烫、防摔或套装件数。',
 'images':['https://www.ikea.com/us/en/images/products/faergklar-mug-matte-green__0986755_pe817319_s5.jpg?f=xl','https://www.ikea.com/us/en/images/products/faergklar-mug-matte-green__0986758_pe817321_s5.jpg?f=xl']},
 'mouse':{'source':'https://www.logitech.com/en-us/shop/p/mx-anywhere-3s.910-006925','deliverable':'Listing 五张附图，不做A+，不需要主图',
 'facts':'Logitech MX Anywhere 3S，Graphite，紧凑型无线鼠标；8K DPI传感器；MagSpeed滚轮有逐格和高速滚动模式；Quiet Clicks比MX Anywhere 3点击噪声更低，不能承诺无声；Easy-Switch可配对最多三台设备；USB-C充电。不得声称Logi Bolt接收器随附，不制作未经验证的性能百分比。',
 'images':['https://resource.logitech.com/content/dam/logitech/en/products/mice/mx-anywhere-3s/product-gallery/graphite/mx-anywhere-3s-mouse-3qtr-front-graphite.png','https://resource.logitech.com/content/dam/logitech/en/products/mice/mx-anywhere-3s/product-gallery/graphite/mx-anywhere-3s-mouse-top-view-graphite.png']},
 'hoodie':{'source':'用户本地商品图 Seattle.png','deliverable':'A+ Basic 五个模块，完整覆盖每个模块的独立图片槽位','facts':'商品外观以Seattle.png为准。未确认材质、保暖防水性能、定制服务和品牌授权，不使用这些承诺。不重复请求B0H2DF4KTQ未知付费状态的MCP。','local':[r'C:\Users\Woda\Desktop\11.4\主图\Seattle.png']}}
def book():return json.loads((OUT/'cases.json').read_text(encoding='utf-8')) if (OUT/'cases.json').exists() else {}
def save(v):(OUT/'cases.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def assets(product,c):
 p=OUT/(product+'-assets.json')
 if p.exists():return json.loads(p.read_text())
 item=PRODUCTS[product];result=[]
 for i,src in enumerate(item.get('images',item.get('local',[]))):
  if src.startswith('https:'):
   r=httpx.get(src,follow_redirects=True,timeout=60);r.raise_for_status();content=r.content;ext='.png' if 'png' in r.headers.get('content-type','') else '.jpg'
  else:content=Path(src).read_bytes();ext=Path(src).suffix
  path=OUT/(product+'-source-'+str(i)+ext);path.write_bytes(content)
  r=c.post(BASE+'/assets',files={'file':(path.name,content,'image/png' if ext=='.png' else 'image/jpeg')},data={'category':'product_reference'});r.raise_for_status()
  result.append({'id':r.json()['id'],'source':src,'path':str(path),'sha256':hashlib.sha256(content).hexdigest()})
 p.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result
def run(name,edit=False):
 c=client();b=book();product=name.split('-')[-1];item=PRODUCTS[product]
 if name not in b:
  a=assets(product,c);text=f'请直接为这个商品生成美国站{item["deliverable"]}。商品官方资料（只用于本次隔离设计验收，不代表我方商品）：{item["source"]}。已核对的事实：{item["facts"]}。参考图是同一款商品的真实外观，保留Logo、颜色、结构。无竞品ASIN，不必询问。未取得的评论与市场数据不能假称已研究，消费动机可明确标为策划假设。自主设计整套方案并并发生成全部图片，不要申请许可。'
  if product=='hoodie':text=text.replace('商品官方资料（只用于本次隔离设计验收，不代表我方商品）','用户提供的商品资料')
  r=c.post(BASE+'/agent/conversations',json={'context_kind':'chat','title':'创意总监对照 · '+name});r.raise_for_status();b[name]={'conversation':r.json()['id'],'text':text,'assets':[x['id'] for x in a],'product':product};save(b)
 v=b[name]
 if 'run' not in v:
  attachment_ids=[]
  for aid in v['assets']:
   r=c.post(BASE+'/agent/conversations/'+v['conversation']+'/attachments',json={'asset_id':aid});r.raise_for_status()
   attachment_ids.append(r.json()['id'])
  r=c.post(BASE+'/agent/conversations/'+v['conversation']+'/messages',json={'content':v['text'],'client_request_id':'creative-20261106-'+name,'chat_mode':True,'auto_execute':True,'attachment_ids':attachment_ids});r.raise_for_status();v['run']=r.json()['id'];save(b)
 r=c.get(BASE+'/agent/runs/'+v['run']);r.raise_for_status();value=r.json();(OUT/(name+'-latest.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'case':name,'run':v['run'],'status':value['status'],'jobs':[(j['capability'],j['status'],j.get('error_code')) for j in value['jobs']],'outputs':len(value.get('outputs',[])),'error':value.get('error_code')},ensure_ascii=False))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('case');a=p.parse_args()
 if a.case=='status':
  for n in book():run(n)
 else:run(a.case)

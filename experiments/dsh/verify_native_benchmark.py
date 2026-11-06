"""Same real assets, task and capped resource pools for the A/B controllers."""
import asyncio,json
from verify_native import client,STATE
TEXT='使用上传的真实商品主图和设计参考，自主选款，为美国站做一整套专业Basic A+并直接并发生成。请按需真实调研竞品B0H2DF4KTQ。商品材质、功能、定制服务和授权未知，不写这些承诺。原图Logo、图案、字样、颜色及背面姓名号码原样保真，模板只借鉴设计。整套五个模块、至少三种真实布局及不同规格的独立图片。每个模块服务不同购买问题，主视觉、人物实景、背面展示、真正局部近拍和细节槽位应改变摄影与构图，避免重复同一正面全身图。信息充分就执行，无须费用或逐张确认。'
async def main():
    c=await client();assets=json.loads((STATE/'native-product-assets.json').read_text(encoding='utf-8'))
    try:
        for controller in ['dsh','langgraph']:
            name='native-ab-'+controller+'-v1'
            response=await c.post('/api/v1/experiment/messages',json={'session':name,'request':name,'controller':controller,'text':TEXT,'asset_ids':[a['id'] for a in assets],'new_task':True})
            response.raise_for_status();result=response.json();(STATE/(name+'-ack.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(name,result['state'],flush=True)
    finally:await c.aclose()
if __name__=='__main__':asyncio.run(main())

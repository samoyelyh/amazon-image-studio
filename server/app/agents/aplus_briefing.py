"""Small persistent clarification boundary, not an intent/tool replacement."""
import re
from app.agents.contracts import AgentPlan,ToolAction


def question(run,context):
    s=run.selection_json
    if not s.get('_aplus_professional') or s.get('request_mode')=='suggest':return None
    if any(s.get(k) for k in ('amazon_plan_id','production_plan_id','parent_output_id','retry_image_job_id','prompt_source_run_id')):return None
    module=(s.get('_creative_context') or {}).get('module','auto')
    if module not in {'auto','amazon_aplus','listing_images'}:return None
    text=(run.result_json.get('reply_context') or {}).get('goal',s['content'])+' '+s.get('_brief_user_reply','')
    if context.get('amazon_plans') and re.search(r'第.{0,3}(?:模块|张|个)|重新|修改|调整|继续',text):return None
    aplus=module=='amazon_aplus' or bool(re.search(r'A\s*\+|A加',text,re.I))
    listing=module=='listing_images' or bool(re.search(r'Listing|主副图|附图',text,re.I))
    suite=bool(re.search(r'一套|整套|全套',text))
    if not (aplus or listing or suite):return None
    kind=None;message=None
    if not aplus and not listing:
        kind='deliverable';message='你想做 Amazon A+ 还是 Listing 附图？有参考的竞品 ASIN 也可以一起发我。'
    elif re.search(r'这件|这款|该商品|参考图|球衣|服装',text) and not context.get('assets'):
        kind='product_reference';message='请上传这款商品的参考图片，我会以真实外观策划，不猜测颜色、图案或功能。'
    elif aplus:
        answered=run.result_json.get('brief_question_answered')
        specific=bool(re.search(r'突出|重点|主要|面向|目标|场景|礼品|送礼|定制|细节|风格|品牌|方向|ASIN|B0[A-Z0-9]{8}',text,re.I))
        direct=bool(re.search(r'直接|不用问|不需要问|不必问|自行|你决定|没有.{0,4}(?:竞品|ASIN)|无.{0,3}ASIN',text,re.I))
        if not answered and not specific and not direct:
            kind='optional_asin';message='有参考的竞品 ASIN 吗？我可以结合竞品卖点与 A+ 布局设计；没有也可以直接做，告诉我你最想突出的方向即可。'
    if not message:return None
    run.result_json={**run.result_json,'aplus_clarification':{'kind':kind,'optional':kind=='optional_asin'}}
    return AgentPlan(summary=message,workflow='dynamic',needs_input=['clarification'],
        actions=[ToolAction(tool='show_message',arguments={'message':message})])

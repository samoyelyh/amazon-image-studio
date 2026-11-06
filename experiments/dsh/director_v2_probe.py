"""Read only known acceptance Jobs; no credentials, broad scans or writes."""
import asyncio,json,sys
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.db.session import get_engine
from app.models.tasks import Job

async def main(ids):
    values=[]
    async with async_sessionmaker(get_engine())() as db:
        for id in ids:
            j=await db.get(Job,id);assert j
            p=j.input_json;meta=p.get('metadata') or {};am=meta.get('amazon_module') or {};trace=am.get('design_trace') or {}
            execution=trace.get('design_execution') or {};prompt=p.get('prompt','')
            values.append({'id':id,'status':j.status,'capability':j.capability,'model':j.model_code if hasattr(j,'model_code') else None,
                'native_role':meta.get('native_role'),'reference_asset_ids':p.get('reference_asset_ids',[]),
                'module_id':am.get('module_id'),'slot_id':am.get('slot_id'),'recipe':meta.get('prompt_recipe_version'),
                'skills':trace.get('skills'),'rule_applications':trace.get('rule_applications'),'design_execution':execution,
                'all_slot_decisions_in_prompt':all(v in prompt for v in execution.values()) if execution else None,
                'all_rule_actions_in_prompt':all(r['decision'] in prompt for r in trace.get('rule_applications',[])) if trace.get('rule_applications') else None,
                'narrative':trace.get('narrative')})
    print(json.dumps(values,ensure_ascii=False))
if __name__=='__main__':asyncio.run(main(sys.argv[1:]))

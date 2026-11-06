"""Read old owners' histories/downloads with scoped platform tokens. No planning."""
import asyncio,json
import httpx
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.core.config import get_settings
from app.db.session import get_engine
from app.models.identity import User
from app.models.agent_control import AgentRun
from app.models.hermes_agent import HermesConversation
from app.models.content import GeneratedOutput,Asset
from app.models.tasks import Job
from app.security.tokens import create_access_token

async def main():
    async with async_sessionmaker(get_engine(),expire_on_commit=False)() as db:
        tests=list((await db.scalars(select(User.id).where(User.account.in_(['dshaccept','dshisolate'])))).all())
        counts={}
        for model,field in [(HermesConversation,HermesConversation.user_id),(AgentRun,AgentRun.user_id),(Job,Job.created_by),(GeneratedOutput,GeneratedOutput.created_by),(Asset,Asset.created_by)]:
            counts[model.__tablename__]=await db.scalar(select(func.count()).select_from(model).where(field.not_in(tests)))
        rows=(await db.scalars(select(AgentRun).where(AgentRun.user_id.not_in(tests),AgentRun.status=='completed').limit(3))).all()
        checks=[]
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000/api/v1',trust_env=False) as client:
            for run in rows:
                user=await db.get(User,run.user_id)
                token,_=create_access_token(get_settings(),run.user_id,run.organization_id,user.token_version)
                r=await client.get('/agent/conversations/'+run.conversation_id,headers={'Authorization':'Bearer '+token})
                assert r.status_code==200
                body=r.json();assert any(v['id']==run.id for v in body['runs'])
                checks.append({'graph':run.graph_version,'status':run.status,'history_http':200,'run_preserved':True})
                outputs=next(v['outputs'] for v in body['runs'] if v['id']==run.id)
                if outputs:
                    r=await client.get('http://127.0.0.1:8000'+outputs[0]['content_url'],headers={'Authorization':'Bearer '+token})
                    assert r.status_code==200;checks[-1]['download_bytes']=len(r.content)
        print(json.dumps({'original_record_counts':counts,'legacy_history_and_download_checks':checks,'model_requests':0}))
if __name__=='__main__':asyncio.run(main())

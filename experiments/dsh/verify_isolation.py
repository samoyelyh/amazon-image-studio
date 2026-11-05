"""Real isolated-DB identities, authenticated file downloads and owner checks."""
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import sys

import httpx
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'server'))
from app.experiments.dsh.environment import configure,STATE
settings=configure()


async def seed():
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import select
    from app.db.session import get_engine
    from app.models.identity import User,Organization,OrganizationMember,Role
    from app.security.passwords import hash_password
    identity=json.loads((STATE/'identity.json').read_text())
    users=[]
    async with async_sessionmaker(get_engine(),expire_on_commit=False)() as db:
        role=await db.scalar(select(Role).where(Role.code=='organization_admin'))
        for index in (1,2):
            org=await db.get(Organization,identity['organization_id'])
            if index==2:
                org=await db.scalar(select(Organization).where(Organization.slug=='dsh-isolation-team'))
                if org is None:org=Organization(name='DSH Isolation Team',slug='dsh-isolation-team');db.add(org);await db.flush()
            account='dsh-isolation-'+str(index)
            user=await db.scalar(select(User).where(User.account==account))
            password=secrets.token_urlsafe(18)
            if user is None:user=User(account=account,display_name=account,password_hash=hash_password(password));db.add(user);await db.flush()
            else:user.password_hash=hash_password(password)
            member=await db.scalar(select(OrganizationMember).where(OrganizationMember.user_id==user.id,OrganizationMember.organization_id==org.id))
            if member is None:db.add(OrganizationMember(user_id=user.id,organization_id=org.id,role_id=role.id))
            users.append((account,password))
        await db.commit()
    return users


async def main():
    cfg=json.loads((STATE/'runtime.json').read_text(encoding='utf-8'))
    initial=json.loads((STATE/'image-dsh-result.json').read_text(encoding='utf-8'))
    edited=json.loads((STATE/'cup-followup.json').read_text(encoding='utf-8'))['result']
    first=initial['run']['outputs'][0];second=edited['run']['outputs'][0]
    evidence=ROOT/'docs'/'dsh'/'evidence';evidence.mkdir(parents=True,exist_ok=True)
    report={'version_chain':second['parent_output_id']==first['id'] and second['version']==2,'owners':[],'downloads':[]}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:18870',timeout=30,trust_env=False) as client:
        result=await client.post('/api/v1/auth/login',json={'account':cfg['BOOTSTRAP_ADMIN_ACCOUNT'],'password':cfg['BOOTSTRAP_ADMIN_PASSWORD']});result.raise_for_status()
        headers={'Authorization':'Bearer '+result.json()['access_token']}
        for i,output in enumerate([first,second],1):
            result=await client.get(output['download_url'],headers=headers);assert result.status_code==200
            file=evidence/('cup-v'+str(i)+'.png');file.write_bytes(result.content)
            with Image.open(file) as image:dimensions=image.size;image.verify()
            report['downloads'].append({'version':i,'sha256':hashlib.sha256(result.content).hexdigest(),'bytes':len(result.content),'dimensions':dimensions})
        assert report['version_chain'] and report['downloads'][0]['sha256']!=report['downloads'][1]['sha256']
        for account,password in await seed():
            result=await client.post('/api/v1/auth/login',json={'account':account,'password':password});result.raise_for_status()
            other={'Authorization':'Bearer '+result.json()['access_token']}
            tickets=await client.get('/api/v1/experiment/tickets',headers=other);assert tickets.json()==[]
            conversation=await client.get('/api/v1/agent/conversations/'+initial['conversation'],headers=other)
            download=await client.get(first['download_url'],headers=other)
            follow=await client.post('/api/v1/experiment/messages',headers=other,json={'session':'live-image-dsh','request':'isolation-'+account,'text':'修改这张图','mode':'continue','ticket':initial['ticket']})
            assert conversation.status_code==404 and download.status_code in {403,404} and follow.status_code==404
            report['owners'].append({'account':account,'tickets':0,'conversation_http':conversation.status_code,'file_http':download.status_code,'forged_followup_http':follow.status_code})
    (evidence/'isolation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    from app.db.session import get_engine
    await get_engine().dispose()


if __name__=='__main__':asyncio.run(main())

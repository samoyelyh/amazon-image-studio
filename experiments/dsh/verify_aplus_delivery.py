"""Verify actual module scope, parent versions, authenticated ZIP and replay."""
import asyncio
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

import httpx
from verify_live import STATE,login

ROOT=Path(__file__).resolve().parents[2]


def call_count():
    with sqlite3.connect(STATE/'worker/budget.sqlite') as db:return db.execute('SELECT count(*) FROM calls').fetchone()[0]


async def main():
    before=json.loads((STATE/'aplus-generate.json').read_text(encoding='utf-8'))['result']
    after=json.loads((STATE/'aplus-module-edit.json').read_text(encoding='utf-8'))['result']
    base=before['run']['outputs'];changed=after['run']['outputs']
    assert len(base)==2 and len(changed)==1
    target=changed[0];original=next(o for o in base if o['amazon_module']['module_id']==target['amazon_module']['module_id'])
    unchanged=next(o for o in base if o['id']!=original['id'])
    assert target['parent_output_id']==original['id'] and target['version']==2
    assert before['ticket']==after['ticket'] and before['conversation']==after['conversation']
    out=ROOT/'docs/dsh/evidence';out.mkdir(parents=True,exist_ok=True)
    async with httpx.AsyncClient(base_url='http://127.0.0.1:18870',trust_env=False,timeout=30) as client:
        await login(client)
        snapshot=call_count()
        repeated=await client.post('/api/v1/experiment/messages',json={'session':'live-amazon','request':'dsh-live-v1-aplus-module-edit',
            'text':'只修改第二个模块：将背景改成明亮的米白色台面，增强杯口和把手的细节光线。第一模块保持不变，不要重新生成第一模块，直接生成第二模块。',
            'controller':'dsh','mode':'continue','ticket':before['ticket'],'new_task':False,'selection':{}})
        repeated.raise_for_status()
        assert repeated.json()['run']['id']==after['run']['id'] and call_count()==snapshot
        downloaded=[]
        for name,o in [('aplus-module-1',unchanged),('aplus-module-2-v1',original),('aplus-module-2-v2',target)]:
            response=await client.get(o['download_url']);response.raise_for_status()
            path=out/(name+'.png');path.write_bytes(response.content)
            downloaded.append({'name':name,'id':o['id'],'sha256':hashlib.sha256(response.content).hexdigest(),'bytes':len(response.content)})
        plan=target['amazon_module']['plan_id'];conv=after['conversation']
        archive=await client.get('/api/v1/agent/conversations/'+conv+'/amazon-plans/'+plan+'/archive');archive.raise_for_status()
        with ZipFile(io.BytesIO(archive.content)) as packed:
            assert packed.testzip() is None
            manifest=json.loads(packed.read('manifest.json'))
            assert not manifest['modules_without_output'] and len(manifest['outputs'])==3
        # Native conversation still contains the original first-module Output.
        history=(await client.get('/api/v1/agent/conversations/'+conv)).json()
        gallery=[o for r in history['runs'] for o in r['outputs']]
        assert any(o['id']==unchanged['id'] for o in gallery)
        report={'same_ticket':True,'same_conversation':True,'original_output_count':2,'revision_output_count':1,'target_module':target['amazon_module']['module_id'],
            'unchanged_module_output':unchanged['id'],'parent_version_correct':True,'replayed_run_unchanged':True,'replay_extra_calls':0,'zip_valid':True,'zip_output_versions':3,'files':downloaded}
        (out/'aplus-delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())

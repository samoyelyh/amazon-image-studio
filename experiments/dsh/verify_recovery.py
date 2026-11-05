"""Run real parallel tasks, restart only controllers during Provider I/O, inspect receipts."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from time import perf_counter

import httpx
from verify_live import login,turn,STATE

ROOT=Path(__file__).resolve().parents[2]
PWSH=Path(r'C:\Users\Woda\Apps\PowerShell\7.4.19\pwsh.exe')


def jobs():
    with sqlite3.connect(STATE/'platform.sqlite') as db:
        return db.execute("SELECT id FROM jobs WHERE capability!='text_generation' AND status='running'").fetchall()


def restart():
    # Scripts verify every PID belongs to this experiment; Workers keep running.
    for script,flag in [('stop.ps1','-ControllerOnly'),('start.ps1','-ControllersOnly')]:
        # Background helpers may inherit pipe handles on Windows. Use a file so
        # communicate() cannot wait forever for those unrelated handles to close.
        with (STATE/('recovery-'+script+'.log')).open('w',encoding='utf-8') as log:
            result=subprocess.run([str(PWSH),'-NoProfile','-File',str(ROOT/'experiments/dsh'/script),flag],cwd=ROOT,stdout=log,stderr=log,timeout=45)
        if result.returncode:raise RuntimeError(script+' failed; see the experiment recovery log')


async def main():
    report={'controller_restart':False}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:18870',trust_env=False,timeout=40) as client:
        await login(client)
        work=asyncio.gather(
            turn(client,'parallel-batch','生成2张黄色无标识陶瓷碗的商品摄影图，一张45度整体展示，一张俯视，不要文字，白色背景。请一次提交两张独立图片并行生成，直接生成。',session='live-concurrency',mode='task',new_task=True,selection={'creative_module':'free_creation'}),
            turn(client,'parallel-other','独立生成1张绿色无标识玻璃瓶的白背景商品摄影图，不要文字，直接生成。',session='live-concurrency',mode='task',new_task=True,selection={'creative_module':'free_creation'}))
        for _ in range(180):
            active=jobs()
            if active:
                before=(await client.get('/api/v1/experiment/tickets',params={'session':'live-concurrency'})).json()
                report['inflight_job_ids']=[r[0] for r in active]
                report['tickets_before']=[{'id':t['id'],'assignments':len(t['assignments'])} for t in before]
                started=perf_counter();await asyncio.to_thread(restart)
                report.update(controller_restart=True,restart_seconds=perf_counter()-started)
                break
            if work.done():break
            await asyncio.sleep(1)
        results=await work
        after=(await client.get('/api/v1/experiment/tickets',params={'session':'live-concurrency'})).json()
        if not report['controller_restart']:
            # Re-running the fixed requests is free. Recover a verifier report
            # from the official durable history if its original process stopped.
            recovered=[t for t in after if any(a.get('endedReason')=='hostRestarted' for a in t['assignments'])]
            if len(recovered)==2:
                from datetime import datetime,timezone
                times=[datetime.fromisoformat(a['endedAt'].replace('Z','+00:00')) for t in recovered for a in t['assignments'] if a.get('endedReason')=='hostRestarted']
                instant=min(times)
                with sqlite3.connect(STATE/'platform.sqlite') as db:
                    rows=db.execute('SELECT j.id,a.provider_requested_at,a.provider_responded_at FROM jobs j JOIN job_attempts a ON a.job_id=j.id').fetchall()
                def parse(v):
                    d=datetime.fromisoformat(v);return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
                active=[id for id,start,end in rows if start and end and parse(start)<instant<parse(end)]
                report.update(controller_restart=True,proof_source='Official persisted hostRestarted Assignments and overlapping real JobAttempt Provider intervals',restart_at_utc=instant.isoformat(),inflight_job_ids=active,
                    tickets_before=[{'id':t['id'],'assignments':len(t['assignments'])-1} for t in recovered])
        report['tickets_after']=[{'id':t['id'],'assignments':len(t['assignments']),'stage':t['stage']} for t in after]
        report['cases']=results
        with sqlite3.connect(STATE/'worker/budget.sqlite') as db:
            report['inflight_call_records']={id:db.execute('SELECT kind,model,state FROM calls WHERE id=?',(id,)).fetchall() for id in report.get('inflight_job_ids',[])}
        report['distinct_tickets']=len({r['result'].get('ticket') for r in results})==2
        report['distinct_conversations']=len({r['result'].get('conversation') for r in results})==2
        report['inflight_calls_not_duplicated']=all(len(v)==1 for v in report['inflight_call_records'].values())
        assert report['distinct_tickets'] and report['distinct_conversations']
        if report['controller_restart']:assert report['inflight_calls_not_duplicated']
        (STATE/'recovery-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False),flush=True)


if __name__=='__main__':asyncio.run(main())

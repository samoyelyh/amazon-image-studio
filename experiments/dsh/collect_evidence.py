"""Export whitelisted measurements; never export runtime secrets or Provider config."""
from collections import Counter
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/'experiments/dsh/.state'
OUT=ROOT/'docs/dsh/evidence'
OUT.mkdir(parents=True,exist_ok=True)


def parse(v):
    if not v:return None
    d=datetime.fromisoformat(v.replace('Z','+00:00'))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def main():
    with sqlite3.connect(STATE/'worker/budget.sqlite') as db:
        rows=db.execute('SELECT id,kind,model,state,started,finished,details FROM calls ORDER BY started').fetchall()
    calls=[];known=Counter();usage_missing=0
    for id,kind,model,state,start,end,raw in rows:
        details=json.loads(raw)
        receipt=STATE/'worker/receipts'/(id+'.json')
        metadata=json.loads(receipt.read_text(encoding='utf-8')).get('metadata') or {} if receipt.is_file() else {}
        usage=details.get('usage') or metadata.get('usage')
        if isinstance(usage,dict):
            for k,v in usage.items():
                if isinstance(v,(int,float)):known[k]+=v
        elif kind=='text':usage_missing+=1
        actual=details.get('actual_requests') if kind=='mcp' else 1
        if kind=='mcp' and details.get('code')=='agent.mcp_schema_changed':actual=0
        if kind=='mcp' and actual is None:actual=1 if state=='succeeded' else None
        calls.append({'job_or_receipt_id':id,'kind':kind,'model':model,'state':state,'actual_requests':actual,
            'duration_seconds':round(end-start,3) if end else None,'usage':usage,'transport':details.get('transport') or metadata.get('transport'),
            'api_cost':details.get('api_cost'),'charged_units':(details.get('result') or {}).get('chargedUnits'),
            'error_code':details.get('code'),'http_status':details.get('http_status')})
    with sqlite3.connect(STATE/'platform.sqlite') as db:
        db.row_factory=sqlite3.Row
        jobs=[dict(r) for r in db.execute('SELECT id,capability,status,model_code,error_code,created_at FROM jobs')]
        attempts=[dict(r) for r in db.execute('SELECT job_id,attempt_number,http_status,error_code,provider_requested_at,provider_responded_at,finished_at FROM job_attempts')]
        runs={r['id']:dict(r) for r in db.execute('SELECT id,status,error_code,created_at FROM agent_runs')}
        links=[tuple(r) for r in db.execute('SELECT run_id,job_id FROM agent_job_links')]
    by_job={r['id']:r for r in jobs}
    cases=[]
    names=['cup-followup','langgraph-baseline','asin-research','aplus-plan','aplus-plan-scoped','aplus-plan-grounded','aplus-plan-no-asin','aplus-generate','aplus-module-edit','parallel-batch','parallel-other']
    for name in names:
        path=STATE/(name+'.json')
        if not path.is_file():continue
        value=json.loads(path.read_text(encoding='utf-8'));result=value.get('result',{});run=result.get('run') or {}
        id=run.get('id');snapshot_ids={j['id'] for j in run.get('jobs',[])}
        related=[by_job[j] for j in snapshot_ids if j in by_job]
        image_times=[parse(j['created_at']) for j in related if j['capability']!='text_generation']
        replay=bool(value.get('replayed_measurement') or related and value.get('completion_seconds',999)<.5)
        end_times=[parse(a['finished_at']) for a in attempts if a['job_id'] in snapshot_ids and a['finished_at']]
        cases.append({'case':name,'controller':value.get('controller'),'state':result.get('state'),
            'error_code':run.get('error_code'),'ticket':result.get('ticket'),'conversation':result.get('conversation'),
            'ack_seconds':None if replay else value.get('ack_seconds'),'completion_seconds':None if replay else value.get('completion_seconds'),
            'cached_replay_seconds':value.get('completion_seconds') if replay else None,
            'durable_run_to_last_job_seconds':round((max(end_times)-parse(runs[id]['created_at'])).total_seconds(),3) if end_times else None,
            'planning_to_first_image_job_seconds':round((min(image_times)-parse(runs[id]['created_at'])).total_seconds(),3) if image_times else None,
            'job_counts':dict(Counter(j['capability'] for j in related)),'output_count':len(run.get('outputs') or []),
            'outputs':[{'id':o['id'],'asset_id':o['asset_id'],'version':o.get('version'),'parent_output_id':o.get('parent_output_id'),'amazon_module':o.get('amazon_module')} for o in run.get('outputs',[])],
            'summary':(run.get('plan') or {}).get('summary')})
    with sqlite3.connect(STATE/'core/dsh.sqlite') as db:
        receipts=[json.loads(v)['result'] for (v,) in db.execute("SELECT value FROM records WHERE kind='receipt'")]
    report={'collected_at':datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).isoformat(),
        'branch':'experiment/dsh-superagent','base_commit':'b838c7cf80db2d46665375ba29dda7b836163d6a','source_snapshot_commit':'502d3601073bbbee0c963215b01c5cb48f2f0246',
        'upstream_commit':'8c32a9dc5d72c033816c6a8110b37f40cf94fba4','limits':{'text':50,'image':50,'mcp':50},
        'actual_requests':{'text':sum(c['actual_requests'] or 0 for c in calls if c['kind']=='text'),'image':sum(c['actual_requests'] or 0 for c in calls if c['kind']=='image'),'mcp_tools_call':sum(c['actual_requests'] or 0 for c in calls if c['kind']=='mcp')},
        'cost':{'currency_amount':None,'known_token_usage':dict(known),'text_calls_without_usage':usage_missing,'note':'No currency cost returned by this Provider. Unknown cost is not zero. MCP chargedUnits also absent. tools/list metadata probes are separate from tools/call.'},
        'dsh_routing_samples':[{'route':r.get('route'),'planning_ms':r.get('planning_ms')} for r in receipts],
        'calls':calls,'cases':cases,'job_attempts':attempts,
        'regression':{'official_core_adapter_node_tests':7,'python_adapter_and_existing_amazon_tests':26,'upstream_windows':{'passed':1155,'failed':42,'unhandled_errors':17,'typecheck':'passed','build':'passed'},'rule_routing_cases':{'passed':14,'total':14,'kind':'deterministic tests; not an LLM accuracy benchmark'}},
        'ui':{'http_and_script_parse':'passed','interactive_browser':'not_accepted','reason':'Browser connector returned timeoutMs errors; native capture returned unavailable/minimized. No browser login or paid browser action was performed.'},
        'limitations':['Official coding Harness booted, but stayed setupPending/repositoryUnset; no DSH coding executor was granted tools or credentials.','The Adapter uses deterministic Main Session routing and the existing LangGraph planner, not the official DSH Main Session LLM.','Controller restart was tested during real image I/O. Killing a Worker after an unknown paid request was not tested and cannot safely imply automatic resend.']}
    recovery=STATE/'recovery-live.json'
    if recovery.is_file():report['recovery']={k:v for k,v in json.loads(recovery.read_text(encoding='utf-8')).items() if k!='cases'}
    chat=STATE/'chat-smoke.json'
    if chat.is_file():
        c=json.loads(chat.read_text(encoding='utf-8'))
        report['plain_chat']={'state':c.get('state'),'route':c.get('route'),'ticket_created':c.get('ticket') is not None,
            'job_capability':by_job.get(c.get('job_id'),{}).get('capability'),'image_jobs_in_turn':0}
    harness=STATE/'harness-state.json'
    if harness.is_file():
        h=json.loads(harness.read_text(encoding='utf-8'));report['official_harness']={'management_api_http':200,'setup_problem':h.get('setup',{}).get('problem'),'runtime':h.get('health',{}).get('runtime'),'load':h.get('load'),'stopped_after_probe':True}
    # Source protection: compare only the explicit code snapshot; no DB scans.
    evidence=ROOT.parent/'dsh-experiment-evidence';original=ROOT.parent/'AI生图'
    manifest=json.loads((evidence/'source-manifest.json').read_text(encoding='utf-8'))
    report['source_protection']={'original_branch':subprocess.check_output(['git','branch','--show-current'],cwd=original,text=True).strip(),
        'original_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=original,text=True).strip(),
        'git_status_unchanged':subprocess.check_output(['git','status','--porcelain=v1','-z'],cwd=original)==(evidence/'original-status.bin').read_bytes(),
        'changed_snapshot_files':[p for p,h in manifest.items() if hashlib.sha256((original/p).read_bytes()).hexdigest()!=h]}
    (OUT/'measurements.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'actual_requests':report['actual_requests'],'known_token_usage':dict(known),'cases':[(c['case'],c['state'],c['output_count']) for c in cases],'source_protection':report['source_protection']},ensure_ascii=False))


if __name__=='__main__':main()

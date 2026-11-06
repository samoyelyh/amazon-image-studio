"""Read-only final acceptance and immutable-output checks, no model submissions."""
import asyncio,hashlib,json,sqlite3
from pathlib import Path
from verify_native import client,STATE,read

async def main():
    c=await client();cases={}
    try:
        for name,session in [('native-real-aplus-v2','native-product-v2'),('native-real-edit-v3','native-product-v2'),('native-ab-dsh-v1','native-ab-dsh-v1'),('native-ab-langgraph-v1','native-ab-langgraph-v1'),('native-listing-v1','native-listing-v1'),('native-research-v1','native-research-v1')]:
            cases[name]=await read(c,name,session)
        original=cases['native-real-aplus-v2'];edit=cases['native-real-edit-v3'];db=sqlite3.connect(STATE/'platform.sqlite')
        assert len(original['run']['outputs'])==8 and len(edit['run']['outputs'])==1
        assert edit['ticket']==original['ticket'] and edit['conversation']==original['conversation']
        output=edit['run']['outputs'][0];assert output['version']==2 and output['amazon_module']['module_id']=='m3_back_detail'
        originals={o['id'] for o in original['run']['outputs']};assert output['parent_output_id'] in originals
        hashes=[]
        for o in original['run']['outputs']:
            response=await c.get(o['download_url']);response.raise_for_status();expected=db.execute('SELECT sha256 FROM assets WHERE id=?',(o['asset_id'],)).fetchone()[0]
            assert hashlib.sha256(response.content).hexdigest()==expected;hashes.append({'output':o['id'],'sha256':expected,'unchanged':True})
        current=original['run']['amazon_plans'][0]['plan'];snapshots={}
        for jid, in db.execute('SELECT job_id FROM agent_job_links WHERE run_id=?',(original['run']['id'],)):
            data=json.loads(db.execute('SELECT input FROM jobs WHERE id=?',(jid,)).fetchone()[0]);m=data['metadata']['amazon_module'];snapshots[m['module_id']]=m['module_snapshot']
        for m in current['modules']:
            if m['id']!='m3_back_detail':assert m==snapshots[m['id']]
            else:assert m['headline']==snapshots[m['id']]['headline'] and m['body']==snapshots[m['id']]['body']
        ledger=sqlite3.connect(STATE/'worker/budget.sqlite');ledger.row_factory=sqlite3.Row
        calls=[dict(r) for r in ledger.execute('SELECT * FROM calls ORDER BY started')]
        for call in calls:call['details']=json.loads(call['details'])
        # The later Kimi-only benchmark has a separately authorized six-call
        # window; preserve the original native acceptance's 50-call boundary.
        kimi_calls=[c for c in calls if c['id'].startswith('kimi-main:')]
        assert len(kimi_calls)<=6
        calls=[c for c in calls if not c['id'].startswith('kimi-main:')]
        counts={kind:sum(c['kind']==kind and c['state']!='not_sent' for c in calls) for kind in ['text','image','mcp']}
        assert counts['text']<=50 and counts['image']<=50 and counts['mcp']<=50
        quota=[]
        for id,balance,reserved in db.execute('SELECT id,balance,reserved_balance FROM quota_accounts'):
            totals=db.execute('SELECT coalesce(sum(balance_delta),0),coalesce(sum(reserved_delta),0) FROM quota_transactions WHERE account_id=?',(id,)).fetchone();assert (balance,reserved)==totals
            quota.append({'account':id,'balanced':True,'balance':balance,'reserved':reserved})
        report={'passed_business_loop':True,'production_cutover_ready':False,'unknown_mcp_outcome':True,
            'original_outputs_unchanged':hashes,'only_changed_module':'m3_back_detail','case_states':{k:v['state'] for k,v in cases.items()},
            'case_outputs':{k:[{x:o.get(x) for x in ['id','asset_id','job_id','width','height','version','parent_output_id','amazon_module']} for o in v.get('run',{}).get('outputs',[])] for k,v in cases.items()},
            'call_counts':counts,'calls':calls,'quota_consistency':quota,
            'limitations':['MCP actual tool request timed out with unknown charge state; do not resend.','Baseline LangGraph blocked on unverified research; no matched image quality comparison.','Native clean A+ planning takes about five minutes; latency acceptance failed.','Image identity and detailed crops still require visual review.','Existing production React Agent UI and 18080 default have not been migrated.']}
        (STATE/'native-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('READ_ONLY_ACCEPTANCE',report['case_states'],'counts',counts)
    finally:await c.aclose()

if __name__=='__main__':asyncio.run(main())

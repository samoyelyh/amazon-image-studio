"""Small reviewable evidence from real Jobs/receipts. Never executes work."""
import json,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from verify_native import STATE

ROOT=Path(__file__).resolve().parents[2]
report=json.loads((STATE/'native-acceptance.json').read_text(encoding='utf-8'))
platform=sqlite3.connect(STATE/'platform.sqlite');platform.row_factory=sqlite3.Row
ledger=sqlite3.connect(STATE/'worker/budget.sqlite');ledger.row_factory=sqlite3.Row
native=sqlite3.connect(STATE/'core/native-control.sqlite');native.row_factory=sqlite3.Row
cases={}
for name in ['native-chat-03','native-clarify-03','native-real-aplus-v2','native-real-edit-v3','native-ab-dsh-v1','native-listing-v1','native-research-v1']:
    r=native.execute("SELECT result FROM requests WHERE json_extract(input,'$.request')=?",(name,)).fetchone()
    if not r:continue
    result=json.loads(r['result']);sessions={result.get(k) for k in ['main_session','vision_session','executor_session']} - {None}
    calls=[]
    for job in platform.execute("SELECT id,model_code,status,input FROM jobs WHERE json_extract(input,'$.metadata.workflow')='dsh_native_session'"):
        inp=json.loads(job['input']);meta=inp['metadata']
        if meta['native_session'] not in sessions:continue
        receipt=ledger.execute('SELECT * FROM calls WHERE id=?',(job['id'],)).fetchone()
        if not receipt:continue
        details=json.loads(receipt['details']);calls.append({'job':job['id'],'session':meta['native_session'],'role':meta['native_role'],'model':job['model_code'],
            'state':receipt['state'],'seconds':round(receipt['finished']-receipt['started'],3) if receipt['finished'] else None,
            'usage':details.get('usage'),'transport':details.get('transport'),'api_cost':details.get('api_cost')})
    cases[name]={'state':result['state'],'ticket':result.get('ticket'),'route_decision':result.get('decision'),'sessions':sorted(sessions),'main_seconds':result.get('main_seconds'),
        'planning_seconds':result.get('seconds'),'calls':calls,'native_events':[{'type':e['type'],'at':e.get('at'),'name':e.get('name')} for e in result.get('events',[])]}

clean=json.loads((STATE/'native-ab-dsh-v1.json').read_text(encoding='utf-8'))
ids=[j['id'] for j in clean['run']['jobs']];intervals=[]
for id in ids:
    row=ledger.execute('SELECT started,finished FROM calls WHERE id=?',(id,)).fetchone()
    if row:intervals.append(tuple(row))
timeline=sorted([(start,1) for start,end in intervals]+[(end,-1) for start,end in intervals if end]);active=peak=0
for at,delta in timeline:active+=delta;peak=max(peak,active)
evidence={'collected_at':datetime.now(timezone.utc).isoformat(),'upstream_core':'8c32a9dc5d72c033816c6a8110b37f40cf94fba4','harness':'0.2.1-rc.3',
    'native_decisions':True,'legacy_planners_in_native_path':False,'production_cutover_ready':False,
    'call_counts':report['call_counts'],'known_token_total':sum((c['details'].get('usage') or {}).get('total_tokens',0) for c in report['calls']),
    'currency_cost':None,'cost_limitation':'The relay supplies token usage but no monetary amount. Unknown calls have no usage receipt.',
    'clean_aplus_peak_provider_concurrency':peak,'clean_aplus_image_seconds':round(max(x[1] for x in intervals)-min(x[0] for x in intervals),3),
    'cases':cases,'acceptance':{k:v for k,v in report.items() if k not in {'calls','case_outputs','original_outputs_unchanged'}},
    'call_attribution_note':'Calls are grouped by persistent Session. A shared Main Session appears in more than one case; do not sum across case lists. The dedicated A/B DSH Session lists exactly its four model calls.',
    'browser':json.loads((STATE/'native-browser.json').read_text(encoding='utf-8')),
    'isolation':json.loads((STATE/'native-isolation.json').read_text(encoding='utf-8')),
    'receipt_recovery':json.loads((STATE/'recorded-result-recovery.json').read_text(encoding='utf-8'))}
folder=ROOT/'docs/dsh/evidence/native';folder.mkdir(exist_ok=True)
(folder/'measurements.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
for source,name in [(STATE/'native-ab-delivery/contact.jpg','aplus-contact.jpg'),(STATE/'native-delivery/contact.jpg','edited-suite-contact.jpg'),(STATE/'native-delivery/browser-restored.jpg','browser-restored.jpg')]:
    if source.is_file():(folder/name).write_bytes(source.read_bytes())
print('METRICS',evidence['call_counts'],'peak',peak,'clean planning',cases['native-ab-dsh-v1']['planning_seconds'],'image_seconds',evidence['clean_aplus_image_seconds'],'tokens',evidence['known_token_total'])

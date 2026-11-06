"""Collect both complete native A+ deliveries and immutable real call evidence."""
import json,sqlite3,io,hashlib
from pathlib import Path
from zipfile import ZipFile
from PIL import Image,ImageDraw,ImageFont,ImageOps
from accept_platform import client,BASE,STATE
from director_v2_accept import OUT,read
ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'docs/dsh/evidence/director-v2'

def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def collect():
    DEST.mkdir(parents=True,exist_ok=True);c=client();case=read()
    r=c.get(BASE+'/agent/conversations/'+case['conversation']);r.raise_for_status();new=r.json();dump(OUT/'conversation.json',new)
    baseline=json.loads((OUT/'baseline.json').read_text(encoding='utf-8'));report={}
    for name,conv in [('before',baseline),('after',new)]:
        plan=conv['amazon_plans'][0]
        r=c.get(BASE+f'/agent/conversations/{conv["id"]}/amazon-plans/{plan["id"]}/archive',timeout=90);r.raise_for_status()
        directory=OUT/name;directory.mkdir(exist_ok=True)
        (directory/'suite.zip').write_bytes(r.content)
        with ZipFile(io.BytesIO(r.content)) as z:
            assert z.testzip() is None
            manifest=json.loads(z.read('manifest.json'))
            for entry in z.infolist():
                p=(directory/'native'/entry.filename).resolve();assert p.is_relative_to((directory/'native').resolve())
                if not entry.is_dir():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(entry))
        if manifest['module_slots_without_output'] or manifest['modules_pending_or_failed']:raise RuntimeError('Incomplete suite: '+name)
        report[name]={'conversation':conv['id'],'plan':plan,'outputs':manifest['outputs'],'source_crops':manifest.get('source_crops',[]),'archive_sha256':hashlib.sha256(r.content).hexdigest()}
        render_native(directory/'native',manifest,DEST/(name+'-suite.jpg'))
    run=next(r for r in new['runs'] if r['id']==case['run'])
    control=sqlite3.connect(STATE/'runtime/core/native-control.sqlite');control.row_factory=sqlite3.Row
    native=json.loads(control.execute('SELECT result FROM requests WHERE id=?',(run['result']['dsh_turn'],)).fetchone()['result'])
    gateway=sqlite3.connect(STATE/'runtime/native-gateway.sqlite');ledger=sqlite3.connect(STATE/'runtime/worker/budget.sqlite');ledger.row_factory=sqlite3.Row
    calls=[]
    for j in run['jobs']:
        row=ledger.execute('select * from calls where id=?',(j['id'],)).fetchone()
        if not row:continue
        detail=json.loads(row['details']);role=gateway.execute('select role from model_jobs where job=?',(j['id'],)).fetchone()
        calls.append({'job':j['id'],'kind':row['kind'],'state':row['state'],'model':row['model'],'role':role[0] if role else None,'seconds':round(row['finished']-row['started'],3) if row['finished'] else None,'started':row['started'],'finished':row['finished'],'usage':detail.get('usage'),'api_cost':detail.get('api_cost')})
    def safe_events(events):
        result=[]
        for e in events:
            if e['type'] in {'main.decision','skill.bound','engine.assignment','tool.error','tool.snapshot_bound'}:result.append(e)
            elif e['type']=='tool.start':result.append({k:v for k,v in e.items() if k in {'at','type','session','name'}})
            elif e['type']=='tool.result':result.append({**{k:v for k,v in e.items() if k in {'at','type','session','name'}},'result':{k:v for k,v in (e.get('result') or {}).items() if k in {'amazon_plan_id','job_ids','module_ids','slot_ids','source_crop_count','reused'}}})
        return result
    report['execution']={'run':run['id'],'ticket':run['result'].get('dsh_ticket'),'sessions':run['result'].get('native_sessions'),'planning_seconds':native.get('seconds'),'main_calls':native.get('main_calls'),'executor_calls':native.get('executor_calls'),'quality':native.get('quality'),'calls':calls,'prompts':run.get('prompts',[]),'events':safe_events(native.get('events',[]))}
    related=[]
    if case.get('edit_run'):related.append(('hero_edit',next(r for r in new['runs'] if r['id']==case['edit_run'])))
    rejected_path=OUT/'rejected-attempt.json'
    if rejected_path.exists():
        rejected=json.loads(rejected_path.read_text(encoding='utf-8'));r=c.get(BASE+'/agent/runs/'+rejected['run']);r.raise_for_status();related.append(('rejected_attempt',r.json()))
    for label,current in related:
        detail=json.loads(control.execute('SELECT result FROM requests WHERE id=?',(current['result']['dsh_turn'],)).fetchone()['result']);current_calls=[]
        for j in current['jobs']:
            row=ledger.execute('select * from calls where id=?',(j['id'],)).fetchone()
            if not row:continue
            value=json.loads(row['details']);role=gateway.execute('select role from model_jobs where job=?',(j['id'],)).fetchone()
            current_calls.append({'job':j['id'],'kind':row['kind'],'state':row['state'],'model':row['model'],'role':role[0] if role else None,'seconds':round(row['finished']-row['started'],3) if row['finished'] else None,'started':row['started'],'finished':row['finished'],'usage':value.get('usage'),'api_cost':value.get('api_cost')})
        report[label]={'run':current['id'],'status':current['status'],'recovery_count':detail.get('recovery_count',0),'quality':detail.get('quality'),'events':safe_events(detail.get('events',[])),'calls':current_calls,'outputs':current.get('outputs',[]),'prompts':current.get('prompts',[])}
    initial=json.loads((OUT/'initial-evidence.json').read_text(encoding='utf-8')) if (OUT/'initial-evidence.json').exists() else None
    if initial:
        original={(o['module_id'],o['slot_id']):o['id'] for o in initial['after']['outputs']}
        final={}
        for o in report['after']['outputs']:
            key=(o['module_id'],o['slot_id'])
            if key not in final or o['version']>final[key]['version']:final[key]=o
        report['local_edit_check']={'unchanged_generated_slots':[list(k) for k,v in original.items() if final[k]['id']==v],
            'changed_generated_slots':[list(k) for k,v in original.items() if final[k]['id']!=v],
            'source_crops_unchanged':initial['after']['source_crops']==report['after']['source_crops'],'latest_generated_count':len(final)}
    dump(DEST/'evidence.json',report)
    before=Image.open(DEST/'before-suite.jpg');after=Image.open(DEST/'after-suite.jpg');combined=Image.new('RGB',(before.width+after.width+24,max(before.height,after.height)),'#dadada');combined.paste(before,(0,0));combined.paste(after,(before.width+24,0));combined.save(DEST/'full-comparison.jpg',quality=91)
    print(json.dumps({'before_images':len(report['before']['outputs']),'after_generated':len(report['after']['outputs']),'after_source_crops':len(report['after']['source_crops']),'planning_seconds':native.get('seconds'),'calls':[{k:v for k,v in x.items() if k in {'kind','role','state','seconds'}} for x in calls]},ensure_ascii=False))
    return report

FONT='C:/Windows/Fonts/msyh.ttc'
def block(text,width,size=17,color='#17202a',bg='white',padding=18):
    font=ImageFont.truetype(FONT,size);lines=[]
    for paragraph in str(text or '').splitlines():
        line=''
        for ch in paragraph:
            if font.getlength(line+ch)>width-2*padding:lines.append(line);line=ch
            else:line+=ch
        lines.append(line)
    step=round(size*1.55);im=Image.new('RGB',(width,max(1,len(lines))*step+2*padding),bg);d=ImageDraw.Draw(im)
    for i,line in enumerate(lines):d.text((padding,padding+i*step),line,font=font,fill=color)
    return im
def stack(parts,width,bg='white'):
    im=Image.new('RGB',(width,sum(p.height for p in parts)),bg);y=0
    for p in parts:im.paste(p,((width-p.width)//2,y));y+=p.height
    return im
def photo(path,width):
    with Image.open(path) as p:return p.convert('RGB').resize((width,round(p.height*width/p.width)),Image.Resampling.LANCZOS)
def row(parts,width,bg='white',gap=14):
    im=Image.new('RGB',(width,max(p.height for p in parts)),bg);x=0
    for p in parts:im.paste(p,(x,(im.height-p.height)//2));x+=p.width+gap
    return im
def render_native(directory,manifest,target):
    """Render the existing native layout types with every slot and exact copy.
    This is a report raster, not a generated image or Seller Central screenshot.
    The adjacent ZIP/preview.html is the actual exported native composition.
    """
    width=650;brief=manifest['brief'];plan=brief['plan'];concept=(plan.get('creative_strategy') or {}).get('concept',{});bg=concept.get('canvas_color','#ffffff');ink=concept.get('ink_color','#17202a')
    latest={}
    for o in manifest['outputs']:
        k=(o['module_id'],o['slot_id'])
        if k not in latest or o['version']>latest[k]['version']:latest[k]=o
    for o in manifest.get('source_crops',[]):latest[(o['module_id'],o['slot_id'])]=o
    parts=[block(('旧版已交付' if target.name.startswith('before') else '新版真实交付')+' · '+concept.get('theme',''),width,23,bg=bg),block('按现有原生模块重排的完整报告图；真实离线预览见同套 ZIP/preview.html。',width,13,bg=bg)]
    for n,m in enumerate(plan['modules'],1):
        spec=brief['module_specs'][m['id']];layout=spec.get('layout','header');slots=spec.get('slots') or [{'id':'main'}];authored={s['id']:s for s in m.get('image_slots',[])}
        def image(s,w):return photo(directory/latest[(m['id'],s['id'])]['archive_path'],w)
        def copy(w):return stack([block(m['headline'],w,23,ink,bg),block(m['body'],w,16,ink,bg)],w,bg)
        if layout in {'image_left','image_right'}:
            a=image(slots[0],(width-14)//2);b=copy((width-14)//2);body=row([a,b] if layout=='image_left' else [b,a],width,bg)
        elif layout in {'three_columns','four_columns','sidebar'}:
            widths=([round((width-14)*2/3),round((width-14)/3)] if layout=='sidebar' else [(width-14*(len(slots)-1))//len(slots)]*len(slots))
            tiles=[]
            for s,w in zip(slots,widths):
                txt=authored.get(s['id'],{});items=[image(s,w)]
                if (m['id'],s['id']) in {(o['module_id'],o['slot_id']) for o in manifest.get('source_crops',[])}:items.append(block('原图局部 · 未生成重绘',w,11,ink,bg,8))
                items.extend([block(txt.get('headline',''),w,17,ink,bg,10),block(txt.get('body',''),w,14,ink,bg,10)])
                tiles.append(stack(items,w,bg))
            body=stack([block(m['headline'],width,23,ink,bg),row(tiles,width,bg),block(m['body'],width,15,ink,bg)],width,bg)
        elif layout=='overlay':
            body=image(slots[0],width);panel=copy(round(width*.42));panel=ImageOps.contain(panel,(panel.width,body.height));body.paste(panel,(width-panel.width,(body.height-panel.height)//2))
        else:body=stack([image(slots[0],width),copy(width)],width,bg)
        parts.extend([block(f'{n}. '+m['title']+' · '+layout,width,14,bg='#ecebe6'),body,Image.new('RGB',(width,18),'#eeeeee')])
    stack(parts,width,bg).save(target,quality=93)
if __name__=='__main__':collect()

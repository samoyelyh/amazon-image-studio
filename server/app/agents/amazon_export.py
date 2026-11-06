"""Owner-scoped handoff package. Original pixels and native text stay separate."""
import html
import io
import json
import re
from tempfile import SpooledTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image
from app.agents import amazon
from app.agents.adapters import chat
from app.core.errors import AppError
from app.models.tasks import Job
from app.services.asset_service import read_asset_content
from app.services.batch_tryon_export_service import _SeekableArchiveReader


def pixel_checks(width, height, spec):
    """Exact project target is not the same as an official minimum requirement."""
    return {
        'dimensions_match':(width,height)==(spec['width'],spec['height']) if spec else None,
        'minimum_pixels_met':width>=spec['minimum_width'] and height>=spec['minimum_height']
            if spec and spec.get('minimum_width') and spec.get('minimum_height') else None,
        'mobile_asset_verified':False if (spec or {}).get('mobile_width') else None,
    }


async def manifest(db, conv, plan_id):
    row, plan = await amazon.record(db, conv, plan_id)
    selected = []
    seen=set()
    for output in await chat.outputs(db, conv):
        if output['id'] in seen:continue
        seen.add(output['id'])
        job = await db.get(Job, output['job_id'])
        meta = (job.input_json.get('metadata') or {}).get('amazon_module', {})
        if meta.get('plan_id') != plan_id:
            continue
        # Historical results are checked against their own immutable submission,
        # never a subsequently edited module or a different rules revision.
        spec = meta.get('spec_snapshot')
        if not spec and meta.get('rules_version') == amazon.rules()['version']:
            spec = amazon.rules()['modules'].get(meta.get('module_snapshot', {}).get('spec_id'))
        selected.append({**output, 'module_id':meta['module_id'],'slot_id':meta.get('slot_id','main'),
            'module_snapshot':meta.get('module_snapshot', {}), 'spec_snapshot':spec,
            **pixel_checks(output['width'],output['height'],spec),
            'format_valid':output['mime_type'] in amazon.rules()['formats']})
    from app.agents.aplus_design import slots
    expected={(m.id,s['id']) for m in plan.modules for s in slots(plan,m)}
    latest_jobs={}
    for submission in row.metadata_json.get('submissions',[]):
        jids=submission.get('job_ids',[])
        for mid,jid,sid in zip(submission.get('module_ids',[]),jids,submission.get('slot_ids') or ['main']*len(jids)):
            latest_jobs[(mid,sid)]=jid
    states=[]
    for (mid,sid),jid in latest_jobs.items():
        job=await db.get(Job,jid)
        states.append({'module_id':mid,'slot_id':sid,'job_id':jid,'status':job.status if job else 'missing',
            'error_code':job.error_code if job else 'job_missing'})
    from app.agents.amazon_contracts import APlusModule
    stale=[]
    for module in plan.modules:
        for slot in slots(plan,module):
            versions=[o for o in selected if o['module_id']==module.id and o['slot_id']==slot['id']]
            latest=max(versions,key=lambda o:o['version']) if versions else None
            if latest and latest.get('module_snapshot') and APlusModule.model_validate(latest['module_snapshot'])!=module:
                stale.append(module.id);break
    return {'brief':amazon.response(row), 'outputs':selected, 'publish_ready':False,
        'modules_without_output':sorted({mid for mid,sid in expected-{(o['module_id'],o['slot_id']) for o in selected}}),
        'module_slots_without_output':[{'module_id':mid,'slot_id':sid} for mid,sid in sorted(expected-{(o['module_id'],o['slot_id']) for o in selected})],
        'latest_module_jobs':states,'modules_pending_or_failed':[s['module_id'] for s in states if s['status']!='succeeded'],
        'modules_with_stale_output':stale,
        'note':'原图和原生文案分离。HTML仅为离线双端审核预览，不可作为Amazon HTML上传；像素/移动端/英文/权利仍需审核。'}


def preview_html(data):
    """Native module/slot composition; escaped text, no scripts or fake pixels."""
    latest={}
    for output in data['outputs']:
        pair=(output['module_id'],output.get('slot_id','main'));prior=latest.get(pair)
        if not prior or output['version']>prior['version']:latest[pair]=output
    esc=lambda value:html.escape(str(value or ''),quote=True)
    sections=[]
    specs=data['brief'].get('module_specs') or {}
    concept=(data['brief']['plan'].get('creative_strategy') or {}).get('concept') or {}
    fonts={'editorial_serif':'Georgia, serif','clean_sans':'Arial, sans-serif','technical_mono':'Consolas, monospace'}
    theme=''
    if concept:
        color=lambda k,d:concept[k] if re.fullmatch(r'#[0-9a-fA-F]{6}',concept.get(k,'')) else d
        theme=f"background:{color('canvas_color','#ffffff')};color:{color('ink_color','#17202a')};border-color:{color('accent_color','#e7e5e4')};font-family:{fonts.get(concept.get('native_type_style'),'Arial, sans-serif')}"
    for module in data['brief']['plan']['modules']:
        spec=specs.get(module['id']) or {};layout=spec.get('layout','header')
        authored={s['id']:s for s in module.get('image_slots',[])}
        slots=spec.get('slots') or [{'id':'main'}]
        pictures=[]
        for slot in slots:
            result=latest.get((module['id'],slot['id']));copy=authored.get(slot['id'],{})
            image=f'<img src="{esc(result["archive_path"])}" alt="{esc(module["title"])} · {esc(slot["id"])}">' if result else f'<p class="missing">槽位 {esc(slot["id"])} 尚无结果</p>'
            pictures.append((slot['id'],image,copy))
        text=f'<div class="copy"><h2>{esc(module["headline"])}</h2><p>{esc(module["body"])}</p></div>'
        if layout in {'image_left','image_right'}:
            content=f'<div class="side {layout}"><div>{pictures[0][1]}</div>{text}</div>'
        elif layout in {'three_columns','four_columns','sidebar'}:
            cells=''.join(f'<div>{image}<h3>{esc(copy.get("headline"))}</h3><p>{esc(copy.get("body"))}</p></div>' for sid,image,copy in pictures)
            content=f'<h2 class="module-title">{esc(module["headline"])}</h2><div class="tiles {layout}">{cells}</div>'
        elif layout=='overlay':
            content=f'<div class="overlay">{pictures[0][1]}{text}</div>'
        else:content=pictures[0][1]+text
        sections.append(f'<section data-module="{esc(module["id"])}" data-layout="{esc(layout)}" style="{esc(theme)}">{content}</section>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'">
<title>A+ module handoff preview</title><style>
body{margin:0;background:#f6f7f9;color:#17202a;font:16px/1.6 system-ui}main{max-width:970px;margin:auto;padding:20px}section{background:white;margin:20px 0;overflow:hidden;border:1px solid #e7e5e4}img{display:block;width:100%;height:auto}.copy{padding:24px;overflow-wrap:anywhere;white-space:pre-wrap}h2{font-size:26px;line-height:1.25;margin:0}h3{font-size:19px}.side{display:grid;grid-template-columns:1fr 1fr;align-items:center}.image_right .copy{grid-column:1;grid-row:1}.image_right>div:first-child{grid-column:2}.tiles{display:grid;gap:20px;padding:24px;overflow-wrap:anywhere}.three_columns{grid-template-columns:repeat(3,minmax(0,1fr))}.four_columns{grid-template-columns:repeat(4,minmax(0,1fr))}.sidebar{grid-template-columns:2fr 1fr}.module-title{padding:24px 24px 0}.overlay{position:relative}.overlay .copy{position:absolute;right:0;top:0;bottom:0;width:36%;display:flex;flex-direction:column;justify-content:center;background:#ffffffdd}.missing{padding:50px;background:#f2f2f2;text-align:center}aside{padding:16px;background:#fff3d6}
@media(max-width:600px){main{padding:8px}.side,.tiles{grid-template-columns:1fr}.image_right .copy,.image_right>div:first-child{grid-column:auto;grid-row:auto}.copy,.tiles{padding:16px}.overlay .copy{position:static;width:auto}h2{font-size:22px}}
</style><main><aside>本平台模块组合审核预览，非 Seller Central 实际渲染或发布文件。独立图片和原生文案分离交付；最终账号权限和展示需运营核对。</aside>'''+''.join(sections)+'</main></html>'


async def archive(db, storage, conv, plan_id):
    data = await manifest(db, conv, plan_id)
    if len(data['outputs']) > 100:
        raise AppError('agent.export_limit','版本图片超过100张，请使用单图下载。',422)
    stream = SpooledTemporaryFile(max_size=8*1024*1024)
    total = 0
    try:
        with ZipFile(stream,'w',ZIP_DEFLATED) as z:
            for output in data['outputs']:
                asset = await chat.asset(db,conv.organization_id,conv.user_id,output['asset_id'])
                raw = await read_asset_content(asset,storage)
                total += len(raw)
                if total > 256*1024*1024:
                    raise AppError('agent.export_limit','导出超过256MB，请分组下载原图。',422)
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        size, fmt, mode = image.size, image.format, image.mode
                        image.verify()
                except Exception:
                    raise AppError('agent.export_corrupt','发现损坏图片，导出已停止，没有静默遗漏。',409) from None
                spec = output['spec_snapshot']
                output.update(width=size[0],height=size[1],**pixel_checks(*size,spec),
                    format_valid=fmt in {'JPEG','PNG'},colorspace_valid=mode in {'RGB','RGBA'},byte_size=len(raw))
                ext = {'JPEG':'jpg','PNG':'png','WEBP':'webp'}.get(fmt,'bin')
                output['archive_path'] = f"images/{output['module_id']}-{output.get('slot_id','main')}-v{output['version']}-{output['id']}.{ext}"
                z.writestr(output['archive_path'],raw)
            z.writestr('manifest.json',json.dumps(data,ensure_ascii=False,indent=2))
            z.writestr('preview.html',preview_html(data))
            z.writestr('copy.json',json.dumps([{'module_id':m['id'],'headline':m['headline'],'body':m['body'],
                'desktop_layout':m['desktop_layout'],'mobile_layout':m['mobile_layout'],'image_slots':m.get('image_slots',[]),
                'copy_source':'current_draft_not_historical_output', 'rules_version':data['brief']['plan']['rules_version'],
                'seller_central_mapping':amazon.rules()['modules'].get(m['spec_id'],{}).get('native_text_fields')
                    if data['brief']['plan']['rules_version']==amazon.rules()['version'] else None,
                'submission_ready':False} for m in data['brief']['plan']['modules']],ensure_ascii=False,indent=2))
        stream.seek(0)
        with ZipFile(_SeekableArchiveReader(stream)) as check:
            if check.testzip() or len(check.namelist()) != len(data['outputs'])+3:
                raise AppError('agent.export_integrity','ZIP完整性验证失败。',500)
        stream.seek(0)
        return stream
    except BaseException:
        stream.close()
        raise

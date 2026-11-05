"""Versioned chat input manifests in existing HermesMessage JSON, never a second queue."""
from datetime import datetime, timezone
from pathlib import PurePath
import re
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field
from sqlalchemy import select
from app.agents.contracts import StrictModel
from app.agents.capabilities.registry import digest
from app.core.errors import AppError
from app.models.hermes_agent import HermesMessage


class ManifestEntry(StrictModel):
    asset_id: str
    filename: str = ''
    sha256: str = ''
    role: str = Field(default='reference', pattern='^(template|garment|reference|front|back|detail|font)$')
    garment_key: str = Field(default='', max_length=160)
    manual: bool = False
    analysis: dict = Field(default_factory=dict)
    enabled:bool=True  # Superseded references remain durable assets, not generation inputs.
    relative_path:str=''
    import_batch_id:str=''
    import_total_files:int=0


class ManifestUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    entries: list[ManifestEntry] = Field(max_length=500)
    pairing_mode: str = Field(default='cartesian', pattern='^(cartesian|paired|custom)$')
    pairs: list[dict[str, str]] = Field(default_factory=list, max_length=500)
    accept_partial_imports:bool=False


class BatchInputManifest(StrictModel):
    schema_version: int = 1
    revision: int = 1
    project_id: str | None = None
    entries: list[ManifestEntry] = Field(default_factory=list, max_length=500)
    pairing_mode: str = 'cartesian'
    pairs: list[dict[str, str]] = Field(default_factory=list, max_length=500)


class ManifestAssignment(StrictModel):
    asset_id:str
    role: str | None = Field(default=None,pattern='^(template|garment|reference|front|back|detail|font)$')
    garment_key: str | None = Field(default=None,max_length=160)


class ManifestPatch(StrictModel):
    expected_revision: int = Field(ge=1)
    assignments: list[ManifestAssignment] = Field(default_factory=list,max_length=500)
    pairing_mode: str | None = Field(default=None,pattern='^(cartesian|paired|custom)$')
    pairs: list[dict[str,str]] | None = Field(default=None,max_length=500)


async def patch(db,conv,payload):
    row=await record(db,conv)
    if row is None:raise AppError('agent.manifest_not_found','请先上传本批素材。',404)
    value=BatchInputManifest.model_validate(row.metadata_json)
    changes={a.asset_id:a.model_dump(exclude_none=True) for a in payload.assignments}
    if set(changes)-{e.asset_id for e in value.entries}:raise AppError('agent.manifest_assets','不能关联其他会话的素材。',403)
    entries=[ManifestEntry.model_validate({**e.model_dump(),**{k:v for k,v in changes.get(e.asset_id,{}).items() if k in {'role','garment_key'}}}) for e in value.entries]
    return await update(db,conv,ManifestUpdate(expected_revision=payload.expected_revision,entries=entries,
        pairing_mode=payload.pairing_mode or value.pairing_mode,pairs=value.pairs if payload.pairs is None else payload.pairs))


def filename_group(filename):
    stem = PurePath(filename).stem.lower()
    sku = re.search(r'(?:nf[-_ ]?)?(\d{7,})', stem)
    if sku:
        return 'sku:' + sku[1]
    return re.sub(r'[-_\s]*(front|back|detail|font|正面|背面|细节|字体|拷贝|copy)(?:[-_\s]*\d+)?$', '', stem).strip(' _-')


def grouped(manifest, conversation_id):
    templates, groups, unresolved = [], {}, []
    for entry in manifest.entries:
        if not entry.enabled:continue
        if entry.role == 'template':
            templates.append({'asset_id': entry.asset_id, 'filename': entry.filename, 'analysis': entry.analysis})
        elif entry.role == 'reference':
            unresolved.append(entry.asset_id)
        elif entry.import_batch_id and not entry.manual and entry.role in ('front','back') and not entry.garment_key:
            unresolved.append(entry.asset_id)  # An AI view label alone does not prove product association.
        else:
            key = entry.garment_key or filename_group(entry.filename) or entry.asset_id
            group = groups.setdefault(key, [])
            group.append(entry)
    garments = []
    for key, entries in groups.items():
        primary = next((e for e in entries if e.role == 'garment'), None) or next((e for e in entries if e.role == 'front'), None) or next((e for e in entries if e.role == 'back'), None)
        if primary is None:
            unresolved.extend(e.asset_id for e in entries)
            continue
        label=primary.filename
        if '/' in primary.relative_path and re.fullmatch(r'(front|back|detail|font|正面|背面|细节|字体)[-_\s]*\d*',PurePath(label).stem,re.I):
            label=(key.removeprefix('sku:') if key.startswith('sku:') else primary.relative_path.rsplit('/',2)[-2])+'-'+label
        garments.append({'id': str(uuid5(NAMESPACE_URL, conversation_id + ':garment:' + key)),
            'key': key, 'label': label, 'primary_asset_id': primary.asset_id,
            'references': {role: [e.asset_id for e in entries if e.role == role] for role in ('garment', 'front', 'back', 'detail', 'font')},
            'asset_ids': [e.asset_id for e in entries]})
    return templates, garments, list(dict.fromkeys(unresolved))


def snapshot(row, manifest):
    templates, garments, unresolved = grouped(manifest, row.conversation_id)
    result = {'id': row.id, 'organization_id': row.organization_id, 'user_id': row.user_id,
        'conversation_id': row.conversation_id, **manifest.model_dump(mode='json'),
        'templates': templates, 'garments': garments, 'unresolved_asset_ids': unresolved}
    # Keep legacy signatures stable when the optional importer is not in use.
    for entry in result['entries']:
        for key in ('relative_path','import_batch_id','import_total_files'):
            if not entry.get(key):entry.pop(key,None)
    signed={**manifest.model_dump(mode='json'),'entries':[dict(e) for e in result['entries']]}
    for entry in signed['entries']:
        if entry.get('enabled') is True:entry.pop('enabled')  # Existing manifest signatures remain valid.
    result['signature'] = digest(signed)
    result['combination_count'] = len(pairs(result))
    crop_required=[]
    if any(e.import_batch_id for e in manifest.entries):
        views={t['analysis'].get('view','auto') for t in templates}
        needed=({'front','back'} if views.intersection({'front_back','auto'}) else views.intersection({'front','back'}))
        by_asset={e.asset_id:e for e in manifest.entries}
        for garment in garments:
            refs=garment['references']
            if any(by_asset[aid].analysis.get('view')=='front_back' for aid in refs['garment']) and any(not refs[v] for v in needed):
                crop_required.append(garment['primary_asset_id'])
        # A mixed original is usable input. Cropping is an optional improvement,
        # not evidence that the requested garment cannot be generated.
        result['crop_recommended_asset_ids']=crop_required
        result['crop_required_asset_ids']=[]  # Retain the existing response field.
    imports={}
    for entry in manifest.entries:
        if entry.import_batch_id:
            batch=imports.setdefault(entry.import_batch_id,{'received':0,'total':entry.import_total_files})
            batch['received']+=1
            batch['total']=max(batch['total'],entry.import_total_files)
    if imports:
        complete=all(b['received']==b['total'] for b in imports.values())
        # Visual predictions do not start another Run. Only changed inputs or
        # human assignments change this key; normal message idempotency persists it.
        key=material_key(manifest)
        result['import_summary']={'batches':imports,'complete':complete,
            'front_bound':sum(bool(g['references']['front']) for g in garments),
            'back_bound':sum(bool(g['references']['back']) for g in garments)}
        result['continuation_key']=key
        result['continue_after_import']=complete and bool(unresolved or templates and garments)
    return result


def material_key(manifest):
    entries=manifest.entries if isinstance(manifest,BatchInputManifest) else [ManifestEntry.model_validate(e) for e in manifest['entries']]
    return digest([[e.asset_id,e.role if e.manual else '',e.garment_key,e.enabled,e.import_batch_id] for e in entries])


def pairs(value):
    tids = [t['asset_id'] for t in value['templates']]
    gids = [g['id'] for g in value['garments']]
    mode = value.get('pairing_mode', 'cartesian')
    if mode == 'paired':
        if len(tids) != len(gids):
            return []
        return list(zip(tids, gids))
    if mode == 'custom':
        return list(dict.fromkeys((p.get('template_asset_id'), p.get('garment_id')) for p in value.get('pairs', [])
            if p.get('template_asset_id') in tids and p.get('garment_id') in gids))
    return [(tid, gid) for tid in tids for gid in gids]


def planning_summary(value):
    if not value:return None
    # Per-asset facts remain in server-side rule compilation, not duplicated in every model turn.
    return {k:value[k] for k in ('id','revision','signature','pairing_mode','pairs','combination_count')} | {
        'asset_count':len(value['entries']),
        'templates':[{k:t[k] for k in ('asset_id','filename')} for t in value['templates']],
        'garments':value['garments'],'unresolved_asset_ids':value['unresolved_asset_ids'][:50],
        'unresolved_count':len(value['unresolved_asset_ids'])}


async def record(db, conv, *, create=False):
    # Sort only narrow columns; JSON is fetched separately (MySQL sort buffer safety).
    ids = list((await db.scalars(select(HermesMessage.id).where(HermesMessage.conversation_id == conv.id,
        HermesMessage.organization_id == conv.organization_id, HermesMessage.user_id == conv.user_id,
        HermesMessage.role == 'batch_input_manifest').order_by(HermesMessage.created_at.desc(), HermesMessage.id.desc()).limit(1))).all())
    row = await db.get(HermesMessage, ids[0]) if ids else None
    if row is None and create:
        row = HermesMessage(conversation_id=conv.id, organization_id=conv.organization_id, user_id=conv.user_id,
            role='batch_input_manifest', content='批量换衣素材清单', metadata_json=BatchInputManifest(project_id=conv.context_project_id).model_dump(mode='json'),
            created_at=datetime.now(timezone.utc))
        db.add(row)
        await db.flush()
    return row


async def sync(db, conv, analyses=None,role_updates=None):
    from app.agents.adapters import chat
    row = await record(db, conv, create=True)
    manifest = BatchInputManifest.model_validate(row.metadata_json)
    old = {e.asset_id: e for e in manifest.entries}
    entries = []
    for attachment in await chat.attachments(db, conv):
        aid = attachment['asset_id']
        entry = old.get(aid) or ManifestEntry(asset_id=aid, filename=attachment['filename'], role=attachment['role'],sha256=attachment.get('sha256',''))
        info=attachment.get('import_info')
        if info:
            entry=entry.model_copy(update={'relative_path':info['relative_path'],'import_batch_id':info['batch_id'],
                'import_total_files':info['total_files']})
            if aid not in old or not entry.garment_key:entry=entry.model_copy(update={'garment_key':attachment.get('garment_key','')})
        if info and aid not in old and attachment['role']!='reference':entry=entry.model_copy(update={'manual':True})
        role_update=(role_updates or {}).get(aid)
        if role_update and (role_update!='reference' or aid in old and old[aid].role!='reference'):
            entry=entry.model_copy(update={'role':role_update,'manual':role_update!='reference'})
        data = (analyses or {}).get(aid)
        if data:
            entry = entry.model_copy(update={'analysis': data})
            if not entry.manual:
                role = attachment['role'] if attachment['role'] != 'reference' else (data['role'] if data.get('confidence',0)>=.8 else 'reference')
                if role == 'garment':
                    suffix = re.search(r'(front|back|detail|font|正面|背面|细节|字体)(?:[-_\s]*\d+)?$', PurePath(entry.filename).stem, re.I)
                    if suffix:
                        role = {'正面':'front','背面':'back','细节':'detail','字体':'font'}.get(suffix[1], suffix[1].lower())
                entry = entry.model_copy(update={'role': role})
        elif aid not in old and attachment['role'] != 'reference':
            entry.manual = True
        entries.append(entry)
    updated = manifest.model_copy(update={'entries': entries, 'project_id': conv.context_project_id})
    if updated.model_dump() != manifest.model_dump():
        updated.revision += 1
        row.metadata_json = updated.model_dump(mode='json')
        await db.flush()
    return snapshot(row, updated)


async def update(db, conv, payload):
    from app.agents.adapters import chat
    row = await record(db, conv)
    if row is None:
        raise AppError('agent.manifest_not_found', '素材清单不存在。', 404)
    old = BatchInputManifest.model_validate(row.metadata_json)
    if old.revision != payload.expected_revision:
        raise AppError('agent.revision_conflict', '素材清单已更新，请刷新后重试。', 409)
    known = {a['asset_id']: a for a in await chat.attachments(db, conv)}
    if len({e.asset_id for e in payload.entries}) != len(payload.entries) or set(known) != {e.asset_id for e in payload.entries}:
        raise AppError('agent.manifest_assets', '每张本会话素材必须且只能出现一次。', 422)
    previous = {e.asset_id:e for e in old.entries}
    entries = [e.model_copy(update={'filename':known[e.asset_id]['filename'],
        'manual':e.role!='reference' and (previous.get(e.asset_id,e).manual or any(getattr(e,k)!=getattr(previous.get(e.asset_id,e),k) for k in ('role','garment_key','enabled'))),
        'sha256':known[e.asset_id].get('sha256',''), 'analysis':previous.get(e.asset_id, e).analysis,
        **{k:getattr(previous.get(e.asset_id,e),k) for k in ('relative_path','import_batch_id','import_total_files')}}) for e in payload.entries]
    if payload.accept_partial_imports:
        counts={}
        for e in entries:
            if e.import_batch_id:counts[e.import_batch_id]=counts.get(e.import_batch_id,0)+1
        changed={e.import_batch_id:{'expected':e.import_total_files,'accepted':counts[e.import_batch_id]} for e in entries
            if e.import_batch_id and e.import_total_files!=counts[e.import_batch_id]}
        entries=[e.model_copy(update={'import_total_files':counts[e.import_batch_id]}) if e.import_batch_id in changed else e for e in entries]
        if changed:
            rows=(await db.scalars(select(HermesMessage).where(HermesMessage.conversation_id==conv.id,HermesMessage.role=='attachment'))).all()
            for a in rows:
                info=(a.metadata_json or {}).get('import_info') or {}
                if info.get('batch_id') in changed:a.metadata_json={**a.metadata_json,'import_info':{**info,'total_files':counts[info['batch_id']]}}
            db.add(HermesMessage(conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,
                role='import_receipt',content='用户选择仅使用已导入的素材继续',metadata_json={'accepted_partial_batches':changed},created_at=datetime.now(timezone.utc)))
    value = BatchInputManifest(revision=old.revision+1, project_id=conv.context_project_id, entries=entries,
        pairing_mode=payload.pairing_mode, pairs=payload.pairs)
    result = snapshot(row, value)
    if payload.pairing_mode == 'paired' and len(result['templates']) != len(result['garments']):
        raise AppError('agent.pair_count', '一一对应要求模板和逻辑服装数量一致。', 422)
    if payload.pairing_mode == 'custom' and len(pairs(result)) != len(payload.pairs):
        raise AppError('agent.invalid_pairs', '指定组合必须引用本清单中的模板和服装，且不能重复。', 422)
    if len(result['templates']) > 10 or len(result['garments']) > 50 or result['combination_count'] > 500:
        raise AppError('agent.matrix_limit', '超过当前10模板、50件逻辑服装或500组合上限。', 422)
    row.metadata_json = value.model_dump(mode='json')
    await db.flush()
    return result


def effective_references(manifest, template_id, garment_id, *, strict=False, warnings=None):
    """The same ordered image B references feed analysis rules and final native Job."""
    template = next(t for t in manifest['templates'] if t['asset_id'] == template_id)
    garment = next(g for g in manifest['garments'] if g['id'] == garment_id)
    view = template['analysis'].get('view', 'auto')
    entries={e['asset_id']:e for e in manifest['entries'] if e.get('enabled',True)}
    refs={role:[aid for aid in ids if aid in entries] for role,ids in garment['references'].items()}
    originals=refs.get('garment',[])
    available=list(dict.fromkeys(originals+refs.get('front',[])+refs.get('back',[])+refs.get('detail',[])))
    available=[aid for aid in available if aid in entries]
    if not available:
        raise AppError('agent.reference_view_missing',f"{garment['label']} 没有可用的服装图片，请补充本件商品参考。",422)
    observed={v for v in ('front','back') if refs.get(v) or any(entries[aid].get('analysis',{}).get('view') in (v,'front_back') for aid in available)}
    needed={'front','back'} if view=='front_back' else {view} if view in ('front','back') else set()
    missing=needed-observed
    if missing:
        labels={'front':'正面','back':'背面'}
        names='、'.join(labels[v] for v in sorted(missing))
        if strict:
            raise AppError('agent.reference_view_missing',f"{garment['label']} 缺少可确认的{names}设计，无法满足本次精确还原要求；请补充对应信息。",422,
                details={'garment_id':garment_id,'missing_views':sorted(missing)})
        if warnings is not None:
            warnings.append(f"{garment['label']} 缺少可确认的{names}设计，使用本件现有素材继续；未见的文字、号码和图案不能作为已知事实，请在样图审核中检查。")
    if view in ('front','back','detail'):
        chosen = refs.get(view) or originals or available[:1]
        if view=='detail' and not refs.get('detail') and warnings is not None:
            warnings.append(f"{garment['label']} 未提供独立细节图，使用现有商品图片；细节清晰度交由样图审核。")
    elif view == 'front_back':
        if refs.get('front') and refs.get('back'):
            chosen=refs['front']+refs['back']
        else:
            chosen=list(dict.fromkeys(originals+refs.get('front',[])+refs.get('back',[]))) or available[:1]
    else:
        chosen = originals or refs.get('front') or refs.get('back') or available[:1]
    if warnings is not None and any(entries.get(aid,{}).get('analysis',{}).get('view')=='front_back' for aid in chosen):
        warnings.append(f"{garment['label']} 使用包含正背面的原图，按模板展示面取用设计；可按需裁剪，样图审核时检查正背内容是否混用。")
    chosen=list(chosen)+[aid for aid in refs.get('detail',[]) if view=='front_back' or any(e['asset_id']==aid and e['analysis'].get('view')==view for e in manifest['entries'])]
    return list(dict.fromkeys(aid for aid in chosen + refs.get('font', []) if aid in entries))

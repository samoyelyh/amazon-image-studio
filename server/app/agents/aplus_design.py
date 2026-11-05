"""Slot specs and deterministic design checks over the existing Amazon plan."""
import re
from difflib import SequenceMatcher
from app.agents.amazon_contracts import ImageSlot

VERSION='professional-aplus-v2'


def slots(plan,module):
    from app.agents.amazon import module_spec
    spec=module_spec(plan,module) or {}
    entries=spec.get('slots') or [{'id':'main',**{k:spec[k] for k in ('width','height','minimum_width','minimum_height') if k in spec}}]
    authored={s.id:s for s in module.image_slots}
    return [{'id':entry['id'],'spec':{**spec,**entry},'direction':authored.get(entry['id']) or
        ImageSlot(id=entry['id'],composition=module.composition)} for entry in entries]


def quality(plan,*,complete=True):
    from app.agents.amazon import module_spec
    errors=[]
    if plan.deliverable!='aplus':return {'version':VERSION,'errors':[],'modules':[]}
    layouts=[];goals=[];report=[]
    if plan.design_version!=VERSION:errors.append('缺少专业设计版本和模块设计依据。')
    if complete and len(plan.modules)<3:errors.append('整套A+叙事不完整，请规划完整模块集合，或说明用户明确要求的较小范围。')
    if complete and len(plan.modules)<5 and not plan.suite_rationale:errors.append('少于五模块时需说明如何完整覆盖本商品的视觉叙事。')
    for m in plan.modules:
        spec=module_spec(plan,m) or {};layout=spec.get('layout',m.spec_id);layouts.append(layout)
        if not spec:errors.append(f'{m.id}: 未知或不适用的Amazon模块规格 {m.spec_id}。')
        elif spec.get('type')!=plan.aplus_type:errors.append(f'{m.id}: 模块类型与本套A+类型不一致。')
        goal=re.sub(r'[\W_]+','',m.main_point.lower());goals.append(goal)
        if len(set(m.design_principles))<3:errors.append(f'{m.id}: 至少明确三项实际应用的设计原则。')
        if not m.art_direction:errors.append(f'{m.id}: 缺少镜头、光线、层级或物理融合设计。')
        actual=slots(plan,m);expected={s['id'] for s in actual};provided=[s.id for s in m.image_slots]
        if (len(expected)>1 or provided) and (set(provided)!=expected or len(provided)!=len(set(provided))):
            errors.append(f'{m.id}: 图片槽位应完整对应 {", ".join(sorted(expected))}，不能以一张拼图代替。')
        if len(expected)>1 and len({s.composition.strip() for s in m.image_slots})!=len(expected):errors.append(f'{m.id}: 每个图片槽位需独立构图。')
        if any(len(s.composition.strip())<5 for s in m.image_slots):errors.append(f'{m.id}: 槽位构图信息不足。')
        report.append({'module_id':m.id,'layout':layout,'official_module_type':spec.get('official_module_type'),
            'principles':m.design_principles,'art_direction':m.art_direction.model_dump() if m.art_direction else None,
            'slots':[{'id':s['id'],'width':s['spec'].get('width'),'height':s['spec'].get('height'),'official_field':s['spec'].get('field')} for s in actual]})
    if len(goals)!=len(set(goals)):errors.append('多个模块主要信息重复，需分别服务不同购买问题。')
    if complete and len(plan.modules)>=4 and len(set(layouts))<3:errors.append('整套A+至少应有三种适合商品的真实模块布局，不能全是横幅。')
    ratios={round(s['spec'].get('width',1)/s['spec'].get('height',1),2) for m in plan.modules for s in slots(plan,m)}
    if complete and len(plan.modules)>=4 and len(ratios)<2:errors.append('整套模块的画面比例缺少变化，请根据用途选择横向主视觉和局部图文等合适模块。')
    if complete and len(plan.modules)>=4 and len({m.art_direction.framing for m in plan.modules if m.art_direction})<3:
        errors.append('镜头景别和主体安排重复，需至少三种服务不同营销目的的画面组织。')
    for i,m in enumerate(plan.modules):
        for n in plan.modules[i+1:]:
            if SequenceMatcher(None,m.composition.strip(),n.composition.strip()).ratio()>.92:
                errors.append(f'{m.id}/{n.id}: 构图近乎重复，应改变景别、主体位置或叙事方式。')
    return {'version':VERSION,'errors':list(dict.fromkeys(errors)),'modules':report,'automated_check':'deterministic_not_visual_acceptance'}

from copy import deepcopy
from io import BytesIO
import hashlib
import pytest
from PIL import Image
from pydantic import ValidationError
from app.agents.amazon_brief import SaveDirectorAPlusV2,normalize_arguments
from app.agents.amazon_contracts import APlusPlan,SourceCrop
from app.agents.professional_prompts import aplus
from app.agents.aplus_design import slots
from app.agents.amazon_source import render_crop
from app.services.image_delivery_service import delivery_prompt_contract
from tests.test_creative_director import director

def director_v2():
    b=director();s=b['creative_strategy'];s.update(version='creative-director-v2',
        priority_method='按商品差异性、用途相关性与事实强度暂定排序；没有评论或销量样本。',rejected_reasons=['抽绳与口袋合并为结构依据，不单独作为主购买理由。'])
    s['concept'].update(big_idea='让城市归属感成为可看见的日常穿搭表达。',visual_mechanism='沿原图胸前图形的弧线组织画面视线，以局部原图证据与动作场景交替形成节奏。',product_specificity='概念连接这款城市图形与渐变颜色，不能替换为无图案普通卫衣。')
    for r in s['purchase_reasons']:r.update(priority_rationale='优先回答与真实商品差异有关的选择问题。',evidence_boundary='外观可见；消费者偏好属于策略假设，无市场样本。')
    for m in b['modules']:
        m['rule_applications']=[{'principle':p,'decision':f'在{m["id"]}中采用{p}对应的具体镜头与原图边缘关系。'} for p in m['design_principles']]
        if not m.get('image_slots'):m['image_slots']=[{'id':'main','composition':m['composition']}]
        for slot in m['image_slots']:slot['design_execution']={'purpose':m['main_point']+'的独立视觉目的','subject_placement':'主体处于右侧三分之一，左侧场景线索从属。','camera':'紧凑斜俯视角观察原图可见图案。','light':'左侧柔和主光与低反差补光。','hierarchy':'原图图案第一，场景次之，精确文案独立。','native_copy_layout':'原生标题先读，支持短句居次，摄影区不造空白面板。','differentiation':'本槽位'+slot['id']+'相较前段改变景别与关系。'}
    return b

def test_v2_requires_actual_prioritization_and_executable_slot_decisions():
    b=director_v2();SaveDirectorAPlusV2(brief=b)
    for change in ('priority','mechanism','slot','rule'):
        bad=deepcopy(b)
        if change=='priority':del bad['creative_strategy']['purchase_reasons'][0]['priority_rationale']
        if change=='mechanism':del bad['creative_strategy']['concept']['visual_mechanism']
        if change=='slot':del bad['modules'][0]['image_slots'][0]['design_execution']
        if change=='rule':bad['modules'][0]['rule_applications']=bad['modules'][0]['rule_applications'][:2]
        with pytest.raises(ValidationError):SaveDirectorAPlusV2(brief=bad)
    no_duplicate=deepcopy(b)
    for m in no_duplicate['modules']:m.pop('design_principles')
    compiled=SaveDirectorAPlusV2(brief=no_duplicate).brief
    assert all(m.design_principles==[r.principle for r in m.rule_applications] for m in compiled.modules)
    source=deepcopy(b);m=source['modules'][0];m['rule_applications']=[{'principle':p,'decision':'直接保留源图可见图案与原有像素。'} for p in ['product_identity','detail_truth']]
    for slot in m['image_slots']:slot.update(source_crop={'asset_id':'asset','box':[0,0,1,1]},design_execution={**slot['design_execution'],'light':'原光'})
    source_compiled=SaveDirectorAPlusV2(brief=source).brief.modules[0]
    assert source_compiled.design_principles==['product_identity','detail_truth','copy_separation']

def test_slot_design_and_skill_actions_survive_final_composer_without_full_product_conflict():
    p=APlusPlan.model_validate(normalize_arguments({'brief':director_v2()})['plan']);m=p.modules[0];slot=slots(p,m)[0]
    prompt=aplus(p,m,slot=slot)
    for value in slot['direction'].design_execution.model_dump().values():assert value in prompt
    for rule in m.rule_applications:assert 'SKILL RULE IN ACTION '+rule.principle+': '+rule.decision in prompt
    assert p.creative_strategy.concept.visual_mechanism in prompt
    assert 'without stretching or cutting off the product' not in prompt
    payload={'requested_width':600,'requested_height':600,'metadata':{'amazon_module':{'design_trace':{'creative_strategy_version':'creative-director-v2'}}}}
    assert 'For an intentional close-up' in delivery_prompt_contract(payload)
    assert 'explicitly authored subordinate graphic elements are allowed' in delivery_prompt_contract(payload)

def test_source_crop_retains_real_pixels_and_does_not_call_a_model():
    source=Image.new('RGB',(8,4));source.putdata([(x*20,y*50,40) for y in range(4) for x in range(8)])
    b=BytesIO();source.save(b,format='PNG');raw=b.getvalue()
    result,trace=render_crop(raw,[.5,0,1,1],(4,4))
    assert list(Image.open(BytesIO(result)).getdata())==list(source.crop((4,0,8,4)).getdata())
    assert trace['source_sha256']==hashlib.sha256(raw).hexdigest() and not trace['upscaled']
    for box in ([0,0,1.1,1],[.7,0,.2,1],[0,0,1,float('nan')]):
        with pytest.raises(ValidationError):SourceCrop(asset_id='owned',box=box)

def test_local_visual_edit_updates_authoritative_prompt_and_preserves_other_slot_signatures():
    from types import SimpleNamespace
    from app.agents.amazon_brief import revise_visual_module
    from app.agents.amazon import slot_signature
    from app.agents.amazon_contracts import ArtDirection
    p=APlusPlan.model_validate(normalize_arguments({'brief':director_v2()})['plan']);m=p.modules[1]
    before={s['id']:slot_signature(p,m,s) for s in slots(p,m)}
    visual=SimpleNamespace(slot_id='block2',composition='非人物的编辑式商业构图：左侧弧形动线连接右侧原商品，深青绿与浅灰分区。',image_prompt='Create an editorial still life. No model or skyline.',art_direction=ArtDirection(framing='非人物俯视场景，商品位于右下角。',lighting='左上方大面积柔光，保留真实色彩。',hierarchy='弧线引向商品印花，原生文案保持独立。',integration='台面接触阴影与尺度透视真实一致。'))
    changed=revise_visual_module(p,m,visual);after={s['id']:slot_signature(p,changed,s) for s in slots(p,changed)}
    assert before['block1']==after['block1'] and before['block3']==after['block3']
    assert before['block2']!=after['block2']
    slot=next(s for s in slots(p,changed) if s['id']=='block2');prompt=aplus(p,changed,slot=slot,editing=True)
    assert visual.art_direction.framing in prompt and visual.art_direction.lighting in prompt
    assert 'Produce one photographic image' not in prompt
    assert 'AUTHORITATIVE SLOT DESIGN CAMERA: '+visual.art_direction.framing in prompt

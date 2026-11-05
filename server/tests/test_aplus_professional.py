"""Professional A+ contracts over native isolated Jobs; no real API calls."""
import io,json
from copy import deepcopy
from zipfile import ZipFile
import pytest
from sqlalchemy import select
from app.models.tasks import Job
from app.agents.amazon_brief import SaveProfessionalBrief,normalize_arguments
from app.agents.amazon_contracts import APlusPlan
from app.agents.aplus_design import quality,slots
from tests.test_agent_control import agent_context
from tests.test_agent_chat_v2 import chat_context,send
from tests.test_agent_second_round import second_context,finish
from tests.test_agent_autonomous import autonomous_context
from tests.test_amazon_advisor import advisor,model_step


def professional_brief(asset):
    titles=['品牌主视觉','姓名号码展示','真实图案细节','穿着场景','礼品情感']
    specs=['basic_header_image_text','basic_three_image_text','basic_single_image_right','basic_image_text_overlay','basic_single_image_left']
    compositions=['横向广角商品主视觉，占画面左侧六成；城市看台形成前后景，侧前柔光保留真实印花，右侧安静留白。',
        '三幅独立画面依次展示姓名区域、号码轮廓与整体前背关系，近景与中景切换，干净浅灰底，文字原生排版。',
        '正面印花的紧凑近景，商品位于右侧，镜头平行图案平面；斜侧柔光展示真实边缘，左侧原生文字讲设计。',
        '日常穿着的动态中景，人物站在球场入口右侧，透视服从身体，暖色轮廓光与冷背景分离，左侧文字。',
        '桌面礼品场景的俯视摄影，衣服完整叠放于素色礼盒旁，柔和窗光形成自然接触阴影，不造新品牌。']
    modules=[]
    for i,(title,spec,comp) in enumerate(zip(titles,specs,compositions),1):
        m={'id':f'm{i}','title':title,'spec_id':spec,'main_point':title,'composition':comp,
            'evidence_ids':['p1','p2'] if i==2 else ['p1'],'copy_space':'none' if i==2 else 'left',
            'headline':['Game-Day Identity','Make It Yours','Original Print Detail','Everyday Fan Style','A Thoughtful Gift'][i-1],
            'body':'Built around your personal style.','design_principles':['product_identity','visual_hierarchy','commercial_lighting','copy_separation'],
            'art_direction':{'framing':comp[:45],'lighting':'左侧大面积柔光为主，轻柔补光保持商品真实黑橙配色，不压暗图案。',
                'hierarchy':title+'为第一视觉信息，背景低对比，原生英文区域不遮挡印花。','integration':'跟随真实透视、布料褶皱和手部遮挡，接触阴影与环境光方向一致。'}}
        if i==2:m['image_slots']=[{'id':f'block{j}','composition':c,'headline':h,'body':'Personal details, clearly shown.'}
            for j,(c,h) in enumerate([('姓名区域正面近景，保留原图字形与准确颜色，不新增无依据名字。','Name Detail'),('号码区域特写，正对平面，真实轮廓、负空间和边缘清晰。','Number Detail'),('整件服装中景展示布局比例，商品占画面七成，留出干净边缘。','Your Design')],1)]
        modules.append(m)
    return {'design_version':'professional-aplus-v2','deliverable':'aplus','marketplace':'US','aplus_type':'basic',
        'suite_rationale':'五模块从识别、定制展示、真实细节、穿着关系到礼品价值，三种以上布局形成完整叙事。',
        'product_identity_lock':'黑橙渐变连帽上衣，保留真实颜色、印花、文字、号码和结构。',
        'campaign_style_lock':'克制黑橙配色、侧向柔光、自然接触阴影，商业摄影与原生英文排版分离。',
        'reference_asset_ids':[asset],'evidence':[{'id':'p1','statement':'参考图是黑橙渐变连帽上衣。'},
            {'id':'p2','statement':'支持定制姓名与号码。','basis':'user_confirmed','source_quote':'本款支持定制姓名与号码'}],
        'modules':modules}


@pytest.fixture
async def pro(advisor):
    advisor['settings'].agent_aplus_professional_enabled=True
    return advisor


def test_five_modules_seven_independent_slots_and_design_checks():
    b=professional_brief('asset');SaveProfessionalBrief.model_validate({'brief':b})
    p=APlusPlan.model_validate(normalize_arguments({'brief':b})['plan'])
    assert not quality(p)['errors'];assert sum(len(slots(p,m)) for m in p.modules)==7
    assert len({(s['spec']['width'],s['spec']['height']) for m in p.modules for s in slots(p,m)})==3
    bad=p.model_copy(deep=True)
    for m in bad.modules:m.spec_id='basic_image_text_overlay';m.image_slots=[]
    assert any('布局' in e for e in quality(bad)['errors'])
    bad=p.model_copy(deep=True);bad.modules[1].image_slots.pop()
    assert any('槽位' in e for e in quality(bad)['errors'])


def test_slot_camera_overrides_module_sequence_and_native_copy_is_external():
    from app.agents.professional_prompts import aplus
    p=APlusPlan.model_validate(normalize_arguments({'brief':professional_brief('asset')})['plan'])
    m=p.modules[1];s=slots(p,m)[1];prompt=aplus(p,m,slot=s)
    assert 'MODULE ART DIRECTION: '+s['direction'].composition in prompt
    assert 'Model-authored scene and camera direction: '+m.composition not in prompt
    assert 'CAMERA AND FRAMING: '+s['direction'].composition in prompt
    assert 'FINAL IMAGE SLOT CONTRACT:' in prompt and 'OUTSIDE this photographic image' in prompt
    assert 'Copy zone:' not in prompt
    assert '图片内部重复预留' in p.modules[2].desktop_layout
    overlay=aplus(p,p.modules[3],slot=slots(p,p.modules[3])[0])
    assert 'OUTSIDE this photographic image' not in overlay
    m.image_prompt='用户编辑的构图要求必须保留。'
    assert m.image_prompt in aplus(p,m,slot=s)


def test_partial_repair_cannot_change_shared_facts_or_unrelated_modules():
    from app.agents.amazon_brief import merge_patch
    from app.agents.capabilities.planning_context import repair_payload,system_prompt,size
    candidate=professional_brief('asset');changed=deepcopy(candidate['modules'][1])
    changed.update(spec_id='basic_single_image_left',image_slots=[],composition='姓名号码区域紧凑中景，只展示参考图已有内容，不承诺未确认服务。')
    result=merge_patch(candidate,{'brief':{'modules':[changed]}},['m2'])['brief']
    assert result['evidence']==candidate['evidence'] and result['campaign_style_lock']==candidate['campaign_style_lock']
    assert result['modules'][0]==candidate['modules'][0] and result['modules'][2:]==candidate['modules'][2:]
    for patch in ({'brief':{'modules':[changed,changed]}},{'brief':{'modules':[candidate['modules'][0]]}},
        {'brief':{'modules':[changed],'product_identity_lock':'wrong'}}):
        with pytest.raises(ValueError):merge_patch(candidate,patch,['m2'])
    context={'creative_context':{'module':'amazon_aplus'},'execution_policy':'autonomous',
        'capability_catalog':[{'id':'business.save_aplus_plan','input_schema':{}}],
        'skill_guidance':[{'id':'amazon-aplus-planner','version':'2','content_hash':'hash','body':'x'*8000}],
        'amazon_rules':{'modules':{}},'history':['x'*10000]}
    compact=repair_payload(context,{'candidate':candidate,'target_ids':['m2'],'errors':['素材超过用户上限']})
    assert not compact['skill_guidance'] and 'history' not in compact
    assert compact['aplus_repair']['candidate_modules']==[candidate['modules'][1]]
    assert size(compact)<size(context) and '不重新策划整套' in system_prompt(compact)


async def test_image_limit_uses_partial_repair_without_resending_images(pro):
    ctx=pro;b=professional_brief(ctx['product']['id'])
    # Seven independent images, but the user's limit is five. No image is sent
    # until the three-slot module is safely reduced to one native image module.
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'brief':b})
    first=await send(ctx,'本款支持定制姓名与号码，直接做整套Basic A+，5个模块，最多5张素材',
        [ctx['product_attachment']['id']],creative_module='amazon_aplus')
    again=await finish(ctx,first)
    assert len(again['jobs'])==2 and all(j['capability']=='text_generation' for j in again['jobs'])
    changed=deepcopy(b['modules'][1]);changed.update(spec_id='basic_single_image_left',image_slots=[])
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'brief':{'modules':[changed]}})
    running=await finish(ctx,again)
    images=[j for j in running['jobs'] if j['capability']!='text_generation']
    assert len(images)==5,running
    assert any(e['type']=='aplus_design_patch_applied' for e in running['events'])
    done=await finish(ctx,running);assert done['status']=='completed'


async def test_ambiguous_request_asks_then_optional_asin_does_not_block_again(pro):
    ctx=pro
    first=await send(ctx,'帮我做一套图',[ctx['product_attachment']['id']])
    assert first['status']=='awaiting_clarification' and not first['jobs']
    assert 'A+' in first['plan']['summary'] and 'Listing' in first['plan']['summary']
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'brief':professional_brief(ctx['product']['id'])})
    second=await send(ctx,'要A+，本款支持定制姓名与号码，突出礼品和穿着场景，直接做')
    assert second['jobs'] and second['result']['brief_question_answered']
    generated=await finish(ctx,second)
    assert generated['status']=='waiting_jobs',generated


async def test_aplus_optional_asin_once_and_clear_request_straight_to_jobs(pro):
    ctx=pro
    first=await send(ctx,'给这件球衣做一套A+',[ctx['product_attachment']['id']],creative_module='amazon_aplus')
    assert first['status']=='awaiting_clarification' and not first['jobs']
    assert 'ASIN' in first['plan']['summary'] and '没有也可以' in first['plan']['summary']
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'brief':professional_brief(ctx['product']['id'])})
    second=await send(ctx,'没有竞品，本款支持定制姓名与号码，突出礼品和穿着场景，直接做')
    assert second['jobs']
    running=await finish(ctx,second);assert running['status']=='waiting_jobs',running
    images=[j for j in running['jobs'] if j['capability']!='text_generation'];assert len(images)==7
    async with ctx['session_factory']() as db:
        jobs=[await db.get(Job,j['id']) for j in images]
        assert len({j.batch_id for j in jobs})==1 and len({j.client_item_id for j in jobs})==7
        assert all('CAMERA AND FRAMING:' in j.input_json['prompt'] and 'APPLIED DESIGN PRINCIPLES:' in j.input_json['prompt'] for j in jobs)
        assert all(j.input_json['metadata']['amazon_module']['design_trace']['skills'] for j in jobs)
    done=await finish(ctx,running);assert done['status']=='completed' and len(done['outputs'])==7
    history=(await ctx['client'].get('/api/v1/agent/conversations/'+ctx['chat']['id'],headers=ctx['headers'])).json()
    plan=history['amazon_plans'][0];assert len(plan['plan']['modules'])==5 and not plan['quality_review']['errors']
    base=f"/api/v1/agent/conversations/{ctx['chat']['id']}/amazon-plans/{plan['id']}"
    packed=await ctx['client'].get(base+'/archive',headers=ctx['headers']);assert packed.status_code==200
    with ZipFile(io.BytesIO(packed.content)) as z:
        assert z.testzip() is None
        manifest=json.loads(z.read('manifest.json'));assert not manifest['module_slots_without_output']
        assert len(manifest['outputs'])==7 and 'three_columns' in z.read('preview.html').decode()
    changed=deepcopy(plan['plan']['modules'][2]);changed['composition']='紧凑电影感近景，右侧真实印花突出，哑光深色背景与窄幅柔光形成高级层次。'
    ctx['mock_decision']=model_step('business.revise_amazon_modules',{'plan_id':plan['id'],'expected_revision':plan['revision'],'modules':[changed]})
    edited=await finish(ctx,await send(ctx,'第三个模块太普通，换一种更有高级感的设计，其他保持不变'))
    assert len([j for j in edited['jobs'] if j['capability']!='text_generation'])==1,edited
    final=await finish(ctx,edited)
    assert len(final['outputs'])==1 and final['outputs'][0]['amazon_module']['module_id']=='m3'
    assert final['outputs'][0]['parent_output_id'] in {o['id'] for o in done['outputs']}


async def test_repeated_or_unsupported_design_replans_once_before_images(pro):
    ctx=pro;b=professional_brief(ctx['product']['id'])
    for m in b['modules']:m['spec_id']='basic_image_text_overlay';m['image_slots']=[]
    ctx['mock_decision']=model_step('business.save_aplus_plan',{'brief':b})
    first=await send(ctx,'本款支持定制姓名与号码，直接做整套专业A+',[ctx['product_attachment']['id']],creative_module='amazon_aplus')
    again=await finish(ctx,first);assert len(again['jobs'])==2 and all(j['capability']=='text_generation' for j in again['jobs'])
    stopped=await finish(ctx,again)
    assert stopped['status'] in {'blocked','failed'} and len(stopped['jobs'])==2,stopped

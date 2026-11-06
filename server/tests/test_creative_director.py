"""Truth links, legacy compatibility and cross-window paid-request safety."""
from copy import deepcopy
import pytest
from pydantic import ValidationError
from app.agents.amazon_brief import SaveDirectorAPlus,normalize_arguments
from app.agents.amazon_contracts import APlusPlan
from app.agents import amazon,professional_prompts
from app.experiments.dsh.ledger import Ledger
from app.providers.base import ProviderError
from tests.test_aplus_professional import professional_brief

def director():
    value=professional_brief('asset')
    value['creative_strategy']={'category':'服装外观验收','research_basis':'market_hypothesis','research_limitations':'无真实评论样本，不承诺定制服务。',
        'purchase_reasons':[{'id':f'r{i}','priority':i,'reason':f'独立购买动机{i}','evidence_ids':['p1'],'consumer_benefit':f'可见外观支持的消费价值{i}','need_or_scene':f'使用场景{i}','confidence':'market_hypothesis','presentation':'visual_and_copy'} for i in range(1,6)],
        'concept':{'theme':'城市色彩的一天','audience':'关注城市风格的消费者','buying_motivation':'通过真实配色表达个人喜好','emotional_tone':'从容日常','distinctive_device':'从大幅城市色块逐步走近原图印花','palette':'黑橙为主体，暖白为呼吸空间','photographic_language':'广角开场、紧凑细节、俯拍收束','typography_and_layout':'原生文字以简洁无衬线分层','narrative':'先建立识别，再展示细节，最后回到日常场景','native_type_style':'clean_sans','canvas_color':'#fff8ef','ink_color':'#202020','accent_color':'#ba5012'},
        'preflight_review':'五条理由是可见设计的消费价值解释，不是五个虚构功能；各模块以不同景别和真实槽位组织，未确认材质和授权已省略。'}
    for i,m in enumerate(value['modules'],1):m['narrative']={'reason_ids':[f'r{i}'],'story_beat':f'叙事段落{i}','shot_purpose':f'通过本段镜头回答购买问题{i}','treatment':'photography'}
    return value

def test_truth_and_reason_links_must_be_complete_without_fabricating_sources():
    value=director();SaveDirectorAPlus(brief=value)
    for key in ('missing_fact','unmapped_reason','bad_priority','fake_mcp','injected_color'):
        b=deepcopy(value)
        if key=='missing_fact':b['creative_strategy']['purchase_reasons'][0]['evidence_ids']=['not-a-fact']
        if key=='unmapped_reason':b['modules'][0]['narrative']['reason_ids']=['r2']
        if key=='bad_priority':b['creative_strategy']['purchase_reasons'][0]['priority']=2
        if key=='fake_mcp':b['creative_strategy']['research_basis']='verified_mcp'
        if key=='injected_color':b['creative_strategy']['concept']['ink_color']='red;display:none'
        with pytest.raises(ValidationError):SaveDirectorAPlus(brief=b)

def test_marketing_decisions_reach_real_composer_and_native_copy_stays_separate():
    p=APlusPlan.model_validate(normalize_arguments({'brief':director()})['plan']);m=p.modules[0]
    prompt=professional_prompts.aplus(p,m)
    assert 'CREATIVE DIRECTOR THEME: 城市色彩的一天' in prompt
    assert 'MAPPED PURCHASE REASON r1' in prompt and 'consumer value:' in prompt
    assert 'MAPPED PURCHASE REASON r2' not in prompt
    assert 'OUTSIDE this photographic image' in prompt
    assert 'unprovided garment faces' not in prompt
    assert m.user_need=='可见外观支持的消费价值1'

def test_new_optional_fields_do_not_change_historical_slot_signatures():
    p=APlusPlan.model_validate(normalize_arguments({'brief':professional_brief('asset')})['plan']);m=p.modules[0]
    raw=m.model_dump(mode='json');raw.pop('narrative');raw.pop('rule_applications')
    for key in ('design_direction','requested_width','requested_height'):
        if raw[key] is None:raw.pop(key)
    expected=amazon.digest({'module':raw,'identity':p.product_identity_lock,'style':p.campaign_style_lock,'rules':p.rules_version,'marketplace':p.marketplace,'evidence':[e.model_dump(mode='json') for e in p.insight.evidence if e.id in m.evidence_ids]})
    assert amazon.module_signature(p,m)==expected

def test_director_listing_uses_its_own_art_language_without_clothing_direction():
    b=director();b['deliverable']='listing';b.pop('design_version');b.pop('suite_rationale')
    for m in b['modules']:m.update(spec_id='listing_square',design_direction=None,image_slots=[])
    p=APlusPlan.model_validate(normalize_arguments({'brief':b})['plan'])
    assert not amazon.findings(p)
    assert 'COMPANY DESIGN DIRECTION:' not in professional_prompts.aplus(p,p.modules[0])

def test_compiler_inherits_reason_facts_without_another_model_round():
    b=director();b['creative_strategy']['purchase_reasons'][0]['evidence_ids']=['p1','p2']
    assert b['modules'][0]['evidence_ids']==['p1']
    p=APlusPlan.model_validate(normalize_arguments({'brief':b})['plan'])
    assert p.modules[0].evidence_ids==['p1','p2']

def test_director_does_not_expand_a_user_quote_into_a_broader_product_fact():
    b=director();b['evidence'][1]['statement']='支持任何颜色与规格的无限定制。'
    p=APlusPlan.model_validate(normalize_arguments({'brief':b})['plan'])
    assert p.insight.evidence[1].statement=='本款支持定制姓名与号码'

def test_new_budget_window_preserves_global_success_and_unknown_receipts(tmp_path):
    old=Ledger(tmp_path,limit=1,window='old');old.reserve('paid','image','m');old.finish('paid','succeeded',{'receipt':'original'})
    new=Ledger(tmp_path,limit=1,window='new');assert new.reserve('paid','image','m')=={'receipt':'original'}
    new.reserve('new-job','image','m')
    with pytest.raises(ProviderError,match='ceiling'):new.reserve('overspend','image','m')
    later=Ledger(tmp_path,limit=1,window='later')
    with pytest.raises(ProviderError,match='resend'):later.reserve('new-job','image','m')
    assert len(later.summary()['calls'])==2

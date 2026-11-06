"""Short model-authored design decisions -> existing APlusPlan/Composer.

This is an internal inference contract, not a new business tool or storage model.
Legacy full SavePlan requests remain valid and use the same execution boundary.
"""
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, model_validator
from app.agents.contracts import StrictModel
from app.agents.creative_strategy import CreativeStrategy,ModuleNarrative,validate_mapping
from app.agents.amazon_contracts import APlusPlan, APlusModule, Evidence, MarketInsight,ArtDirection,ImageSlot,DesignPrinciple

VERSION='amazon-design-decisions-v1'


class BriefEvidence(StrictModel):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    statement:str=Field(min_length=1,max_length=500,description='Only visible product facts or explicit user facts, not competitor claims.')
    basis:Literal['visible_reference','user_confirmed']='visible_reference'
    source_quote:str=Field(default='',max_length=500,description='For user_confirmed facts, quote exact words from an actual user message; never quote model analysis.')


class ModuleDecision(StrictModel):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    title:str=Field(min_length=1,max_length=80)
    spec_id:str|None=Field(default=None,max_length=80,
        description='Only needed when selecting among multiple approved specs. Listing uses listing_square; a unique approved Basic/Premium spec is inherited.')
    main_point:str=Field(min_length=1,max_length=300)
    composition:str=Field(min_length=1,max_length=1500,description='Concise art direction, preferably 60-100 Chinese characters: subject, framing, scene, light, hierarchy. Not a full image prompt. The validation ceiling allows a longer valid multilingual brief without truncation.')
    evidence_ids:list[str]=Field(min_length=1,max_length=8)
    design_direction:Literal['white','custom','watch','gift','detail','casual']|None=None
    copy_space:Literal['left','right','top','bottom','none']='right'
    headline:str=Field(default='',max_length=80)
    body:str=Field(default='',max_length=300)
    reference_asset_ids:list[str]|None=Field(default=None,min_length=1,max_length=10,
        description='Only if this module needs different references; otherwise inherit the shared list.')
    requested_width:int|None=Field(default=None,ge=256,le=4096)
    requested_height:int|None=Field(default=None,ge=256,le=4096)
    design_principles:list[DesignPrinciple]=Field(default_factory=list,max_length=9)
    art_direction:ArtDirection|None=None
    image_slots:list[ImageSlot]=Field(default_factory=list,max_length=4)
    narrative:ModuleNarrative|None=None


class DesignBrief(StrictModel):
    deliverable:Literal['aplus','listing']
    marketplace:Literal['US','UK','CA','DE','FR','IT','ES','JP','AU']
    aplus_type:Literal['basic','premium']='basic'
    product_identity_lock:str=Field(min_length=1,max_length=1000)
    campaign_style_lock:str=Field(min_length=1,max_length=800)
    reference_asset_ids:list[str]=Field(min_length=1,max_length=10)
    evidence:list[BriefEvidence]=Field(min_length=1,max_length=12)
    # Market insights remain the model's decision input. Do not copy raw MCP
    # receipts/reviews back into the reply or relabel them as own-product facts.
    market_basis:str=Field(default='',max_length=400)
    risks:list[str]=Field(default_factory=list,max_length=10)
    modules:list[ModuleDecision]=Field(min_length=1,max_length=7)
    creative_strategy:CreativeStrategy|None=None

    @model_validator(mode='after')
    def stable_ids_and_evidence(self):
        for values in (self.modules,self.evidence):
            if len({v.id for v in values})!=len(values):raise ValueError('ids must be unique')
        evidence={e.id for e in self.evidence}
        if any(set(m.evidence_ids)-evidence for m in self.modules):raise ValueError('module evidence must exist')
        if self.creative_strategy:validate_mapping(self.creative_strategy,self.modules,evidence,compiled=False)
        return self


class SaveDesignBrief(StrictModel):
    brief:DesignBrief


class ProfessionalModuleDecision(ModuleDecision):
    spec_id:str=Field(min_length=1,max_length=80)
    design_principles:list[DesignPrinciple]=Field(min_length=3,max_length=9)
    art_direction:ArtDirection


class ProfessionalDesignBrief(DesignBrief):
    design_version:Literal['professional-aplus-v2']
    suite_rationale:str=Field(min_length=5,max_length=500)
    modules:list[ProfessionalModuleDecision]=Field(min_length=1,max_length=7)


class SaveProfessionalBrief(StrictModel):
    brief:ProfessionalDesignBrief

class DirectorModuleDecision(ProfessionalModuleDecision):
    narrative:ModuleNarrative

class DirectorAPlusBrief(ProfessionalDesignBrief):
    creative_strategy:CreativeStrategy
    modules:list[DirectorModuleDecision]=Field(min_length=1,max_length=7)

class DirectorListingBrief(DesignBrief):
    creative_strategy:CreativeStrategy
    modules:list[DirectorModuleDecision]=Field(min_length=1,max_length=7)

class SaveDirectorAPlus(StrictModel):
    brief:DirectorAPlusBrief

class SaveDirectorListing(StrictModel):
    brief:DirectorListingBrief


class BriefPatch(StrictModel):
    modules:list[ProfessionalModuleDecision]=Field(min_length=1,max_length=5)


class SaveBriefPatch(StrictModel):
    brief:BriefPatch


def merge_patch(candidate,patch,allowed_ids):
    """Model may replace only known affected modules, never shared facts/locks."""
    from copy import deepcopy
    value=SaveBriefPatch.model_validate(patch)
    changed={m.id:m.model_dump(mode='json') for m in value.brief.modules}
    if len(changed)!=len(value.brief.modules) or set(changed)-set(allowed_ids):
        raise ValueError('repair scope mismatch')
    if set(changed)-{m['id'] for m in candidate['modules']}:
        raise ValueError('repair module does not exist')
    result=deepcopy(candidate)
    result['modules']=[changed.get(m['id'],m) for m in result['modules']]
    ProfessionalDesignBrief.model_validate(result)
    return {'brief':result}


def expand(brief:DesignBrief, *, collected_at=None):
    """No LLM/HTTP call: compile to the unchanged, owner-checked SavePlan."""
    from app.agents import amazon, professional_prompts
    timestamp=collected_at or datetime.now(timezone.utc)
    evidence=[Evidence(id=e.id,statement=e.source_quote if brief.creative_strategy and e.basis=='user_confirmed' else e.statement,source=('用户确认引文：'+e.source_quote) if e.basis=='user_confirmed' else '本会话已授权商品参考图',
        collected_at=timestamp,scope='own_product',status='fact') for e in brief.evidence]
    modules=[]
    for m in brief.modules:
        linked=[e for r in brief.creative_strategy.purchase_reasons if m.narrative and r.id in m.narrative.reason_ids for e in r.evidence_ids] if brief.creative_strategy else []
        module_evidence=list(dict.fromkeys([*m.evidence_ids,*linked]))
        spec_id=m.spec_id
        if not spec_id:
            if brief.deliverable=='listing':spec_id='listing_square'
            else:
                # Legacy briefs retain their previous implicit spec. New
                # professional briefs must choose a reviewed module explicitly.
                choices=['basic_image_text_overlay'] if brief.aplus_type=='basic' else ['premium_full_image']
                if len(choices)!=1:
                    from app.core.errors import AppError
                    raise AppError('agent.amazon_spec_missing',f'{m.id}: 存在多个模块规格，请明确选择。',422)
                spec_id=choices[0]
        desktop=(f'保留{m.copy_space}侧安静文案区；商品与关键设计不进入文字区。'
            if m.copy_space!='none' else '商品画面优先，不新增营销排版文字。')
        if getattr(brief,'design_version','legacy')=='professional-aplus-v2':
            spec=amazon.rules()['modules'].get(spec_id,{})
            if spec.get('layout') in {'header','image_left','image_right','three_columns','sidebar'}:
                desktop='英文标题与正文位于Amazon原生图文区域；摄影图片完整利用自身画幅，不在图片内部重复预留空白文字面板。'
        module=APlusModule(id=m.id,title=m.title,spec_id=spec_id,main_point=m.main_point,
            user_need=('；'.join(r.consumer_benefit for r in brief.creative_strategy.purchase_reasons if m.narrative and r.id in m.narrative.reason_ids) if brief.creative_strategy else m.main_point),evidence_ids=module_evidence,composition=m.composition,
            image_prompt=professional_prompts.module_decision(m),
            reference_asset_ids=m.reference_asset_ids or brief.reference_asset_ids,
            headline=m.headline,body=m.body,desktop_layout=desktop,
            mobile_layout='保留商品、Logo和主要图案完整可见；文字单独排版，移动端按主体安全区审核。',
            acceptance=amazon.rules()['manual_checks'],design_direction=m.design_direction,
            requested_width=m.requested_width,requested_height=m.requested_height,
            design_principles=m.design_principles,art_direction=m.art_direction,image_slots=m.image_slots,narrative=m.narrative)
        modules.append(module)
    return APlusPlan(deliverable=brief.deliverable,marketplace=brief.marketplace,aplus_type=brief.aplus_type,
        rules_version=amazon.rules()['version'],product_identity_lock=brief.product_identity_lock,
        campaign_style_lock=brief.campaign_style_lock,
        design_version=getattr(brief,'design_version','legacy'),suite_rationale=getattr(brief,'suite_rationale',''),
        creative_strategy=brief.creative_strategy,
        insight=MarketInsight(visual_opportunities=[brief.market_basis] if brief.market_basis else [],
            limitations=brief.risks,evidence=evidence),modules=modules)


def normalize_arguments(arguments):
    if 'brief' not in arguments:return arguments
    model=SaveProfessionalBrief if (arguments.get('brief') or {}).get('design_version')=='professional-aplus-v2' else SaveDesignBrief
    request=model.model_validate(arguments)
    return {'plan':expand(request.brief).model_dump(mode='json')}

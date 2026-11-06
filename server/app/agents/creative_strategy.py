"""Model-authored marketing and art decisions. No category templates or aesthetic scores."""
from typing import Literal
from pydantic import Field,model_validator
from app.agents.contracts import StrictModel

class PurchaseReason(StrictModel):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    priority:int=Field(ge=1,le=5)
    reason:str=Field(min_length=3,max_length=200)
    evidence_ids:list[str]=Field(min_length=1,max_length=8)
    consumer_benefit:str=Field(min_length=3,max_length=300)
    need_or_scene:str=Field(min_length=3,max_length=200)
    confidence:Literal['fact_grounded_interpretation','market_hypothesis']
    presentation:Literal['visual','native_copy','visual_and_copy','internal_only']
    priority_rationale:str|None=Field(default=None,max_length=300)
    evidence_boundary:str|None=Field(default=None,max_length=300,description='What is observed, what is a creative hypothesis, and what is NOT established by market data.')

class CreativeConcept(StrictModel):
    theme:str=Field(min_length=3,max_length=100)
    audience:str=Field(min_length=3,max_length=200)
    buying_motivation:str=Field(min_length=3,max_length=200)
    emotional_tone:str=Field(min_length=3,max_length=150)
    distinctive_device:str=Field(min_length=5,max_length=300,description='A specific memorable visual idea, not adjectives.')
    palette:str=Field(min_length=5,max_length=250)
    photographic_language:str=Field(min_length=5,max_length=300)
    typography_and_layout:str=Field(min_length=5,max_length=250)
    narrative:str=Field(min_length=5,max_length=400)
    native_type_style:Literal['editorial_serif','clean_sans','technical_mono']
    canvas_color:str=Field(pattern=r'^#[0-9a-fA-F]{6}$')
    ink_color:str=Field(pattern=r'^#[0-9a-fA-F]{6}$')
    accent_color:str=Field(pattern=r'^#[0-9a-fA-F]{6}$')
    big_idea:str|None=Field(default=None,max_length=300)
    visual_mechanism:str|None=Field(default=None,max_length=400,description='The concrete visual operation linking product identity to consumer value; not a palette or mood.')
    product_specificity:str|None=Field(default=None,max_length=250,description='Why this concept belongs to this product rather than any generic product.')

class CreativeStrategy(StrictModel):
    version:Literal['creative-director-v1','creative-director-v2']='creative-director-v1'
    category:str=Field(min_length=2,max_length=100)
    research_basis:Literal['market_hypothesis','provided_context','verified_mcp']
    research_receipt_ids:list[str]=Field(default_factory=list,max_length=10)
    research_limitations:str=Field(min_length=3,max_length=300)
    purchase_reasons:list[PurchaseReason]=Field(min_length=5,max_length=5)
    concept:CreativeConcept
    preflight_review:str=Field(min_length=20,max_length=600,description='Explain fact limits, consumer value, shot rhythm, module fit and what was deliberately omitted. No numeric taste score.')
    priority_method:str|None=Field(default=None,max_length=350)
    rejected_reasons:list[str]|None=Field(default=None,max_length=6,description='Weak, duplicate or unsupported selling points deliberately merged or omitted, with reasons.')
    @model_validator(mode='after')
    def distinct(self):
        if len({r.id for r in self.purchase_reasons})!=5 or {r.priority for r in self.purchase_reasons}!={1,2,3,4,5}:raise ValueError('five reasons need unique ids and priorities 1..5')
        if self.research_basis=='verified_mcp' and not self.research_receipt_ids:raise ValueError('verified MCP requires real receipt ids')
        return self

class PurchaseReasonV2(PurchaseReason):
    priority_rationale:str=Field(min_length=5,max_length=300)
    evidence_boundary:str=Field(min_length=5,max_length=300)

class CreativeConceptV2(CreativeConcept):
    big_idea:str=Field(min_length=10,max_length=300)
    visual_mechanism:str=Field(min_length=10,max_length=400)
    product_specificity:str=Field(min_length=10,max_length=250)

class CreativeStrategyV2(CreativeStrategy):
    version:Literal['creative-director-v2']
    priority_method:str=Field(min_length=10,max_length=350)
    rejected_reasons:list[str]=Field(min_length=1,max_length=6)
    purchase_reasons:list[PurchaseReasonV2]=Field(min_length=5,max_length=5)
    concept:CreativeConceptV2

class ModuleNarrative(StrictModel):
    reason_ids:list[str]=Field(min_length=1,max_length=5)
    story_beat:str=Field(min_length=3,max_length=150)
    shot_purpose:str=Field(min_length=5,max_length=250)
    treatment:Literal['photography','detail','lifestyle','native_infographic','brand_visual']

def validate_mapping(strategy,modules,evidence_ids,*,compiled=True):
    reasons={r.id:r for r in strategy.purchase_reasons}
    for r in reasons.values():
        if set(r.evidence_ids)-set(evidence_ids):raise ValueError('purchase reasons must cite existing own-product facts')
    used=set()
    for m in modules:
        if not m.narrative or set(m.narrative.reason_ids)-reasons.keys():raise ValueError(f'{m.id}: narrative.reason_ids must reference existing purchase reason ids')
        used.update(m.narrative.reason_ids)
        linked={e for rid in m.narrative.reason_ids for e in reasons[rid].evidence_ids}
        if compiled and not linked<=set(m.evidence_ids):raise ValueError(f'{m.id}: compiled module is missing purchase reason facts')
    if {r.id for r in reasons.values() if r.presentation!='internal_only'}-used:raise ValueError('all public purchase reasons must be mapped to modules, not necessarily one-to-one')

class QualityFinding(StrictModel):
    output_ids:list[str]=Field(min_length=1,max_length=10)
    observation:str=Field(min_length=5,max_length=500)
    recommendation:str=Field(min_length=3,max_length=350)
    severity:Literal['review','must_fix']

class VisualQualityReview(StrictModel):
    plan_id:str
    expected_revision:int=Field(ge=1)
    inspected_output_ids:list[str]=Field(min_length=1,max_length=10)
    consistency:str=Field(min_length=5,max_length=500)
    narrative_and_rhythm:str=Field(min_length=5,max_length=500)
    identity_fidelity:str=Field(min_length=5,max_length=500)
    copy_alignment:str=Field(min_length=5,max_length=500)
    findings:list[QualityFinding]=Field(default_factory=list,max_length=12)
    limitations:str=Field(min_length=5,max_length=400)

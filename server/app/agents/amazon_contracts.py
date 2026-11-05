"""Typed chat records; stored in existing HermesMessage metadata, not a new queue."""
from typing import Literal
from datetime import datetime
from pydantic import Field, model_validator
from app.agents.contracts import StrictModel


class Evidence(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    statement: str = Field(min_length=1, max_length=1500)
    source: str = Field(min_length=1, max_length=1000)
    collected_at: datetime
    scope: Literal['own_product', 'competitor', 'market']
    status: Literal['fact', 'estimate', 'hypothesis', 'unknown']
    asin: str | None = Field(default=None, pattern=r'^[A-Z0-9]{10}$')
    period: str = Field(default='', max_length=200)
    review_sample_count: int | None = Field(default=None, ge=0)
    review_scope: str = Field(default='', max_length=300)


class MarketInsight(StrictModel):
    customers_and_scenes: list[str] = Field(default_factory=list, max_length=20)
    competitor_points: list[str] = Field(default_factory=list, max_length=20)
    buyer_concerns: list[str] = Field(default_factory=list, max_length=20)
    keywords_and_intent: list[str] = Field(default_factory=list, max_length=30)
    visual_opportunities: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)


DesignPrinciple=Literal['product_identity','campaign_consistency','visual_hierarchy','commercial_lighting','scale_context','detail_truth','emotional_story','copy_separation','multi_slot_storytelling']


class ArtDirection(StrictModel):
    framing:str=Field(min_length=3,max_length=400)
    lighting:str=Field(min_length=3,max_length=400)
    hierarchy:str=Field(min_length=3,max_length=400)
    integration:str=Field(min_length=3,max_length=400)


class ImageSlot(StrictModel):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    composition:str=Field(min_length=1,max_length=1200)
    headline:str=Field(default='',max_length=160)
    body:str=Field(default='',max_length=1000)
    reference_asset_ids:list[str]|None=Field(default=None,min_length=1,max_length=10)


class APlusModule(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    title: str = Field(min_length=1, max_length=150)
    spec_id: str = Field(max_length=80)
    main_point: str = Field(min_length=1, max_length=1000)
    user_need: str = Field(default='', max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    composition: str = Field(min_length=1, max_length=3000)
    image_prompt: str = Field(min_length=1, max_length=10000)
    reference_asset_ids: list[str] = Field(min_length=1, max_length=10)
    headline: str = Field(default='', max_length=150)
    body: str = Field(default='', max_length=2000)
    desktop_layout: str = Field(min_length=1, max_length=2000)
    mobile_layout: str = Field(min_length=1, max_length=2000)
    prohibited: list[str] = Field(default_factory=list, max_length=30)
    acceptance: list[str] = Field(default_factory=list, max_length=30)
    design_direction: Literal['white', 'custom', 'watch', 'gift', 'detail', 'casual'] | None = None
    requested_width: int | None = Field(default=None, ge=256, le=4096)
    requested_height: int | None = Field(default=None, ge=256, le=4096)
    design_principles:list[DesignPrinciple]=Field(default_factory=list,max_length=9)
    art_direction:ArtDirection|None=None
    image_slots:list[ImageSlot]=Field(default_factory=list,max_length=4)


class APlusPlan(StrictModel):
    deliverable: Literal['aplus', 'listing'] = 'aplus'
    marketplace: Literal['US', 'UK', 'CA', 'DE', 'FR', 'IT', 'ES', 'JP', 'AU']
    aplus_type: Literal['basic', 'premium'] = 'basic'
    rules_version: str
    product_identity_lock: str = Field(min_length=1, max_length=3000)
    campaign_style_lock: str = Field(min_length=1, max_length=3000)
    insight: MarketInsight
    modules: list[APlusModule] = Field(min_length=1, max_length=7)
    design_version:str='legacy'
    suite_rationale:str=Field(default='',max_length=500)
    @model_validator(mode='after')
    def unique_ids(self):
        for values in (self.modules, self.insight.evidence):
            if len({v.id for v in values}) != len(values): raise ValueError('ids must be unique')
        return self


class SavePlan(StrictModel):
    plan: APlusPlan


class ModuleRevision(StrictModel):
    plan_id: str
    expected_revision: int = Field(ge=1)
    module: APlusModule


class ModuleRevisions(StrictModel):
    plan_id: str
    expected_revision: int = Field(ge=1)
    modules: list[APlusModule] = Field(min_length=1, max_length=7)

    @model_validator(mode='after')
    def unique_modules(self):
        if len({m.id for m in self.modules}) != len(self.modules):
            raise ValueError('module ids must be unique')
        return self


class ModuleApproval(StrictModel):
    expected_revision: int = Field(ge=1)
    module_ids: list[str] = Field(min_length=1, max_length=7)
    verified_evidence_ids: list[str] = Field(min_length=1, max_length=100)
    commercial_rights_confirmed: bool


class GenerateAPlus(StrictModel):
    plan_id: str
    expected_revision: int = Field(ge=1)
    module_ids: list[str] = Field(min_length=1, max_length=7)
    retry_failed: bool = False

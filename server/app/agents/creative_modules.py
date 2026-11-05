"""Owner-scoped conversation expertise; a preference, never a tool permission grant."""
from datetime import datetime,timezone
from typing import Literal
from uuid import NAMESPACE_URL,uuid5
from pydantic import Field
from sqlalchemy import select
from app.agents.contracts import StrictModel
from app.core.errors import AppError
from app.models.hermes_agent import HermesMessage

ModuleCode=Literal['auto','amazon_aplus','batch_tryon','listing_images','free_creation','image_edit']
MODULES={
 'auto':('自动选择',[],''),
 'amazon_aplus':('A+ 内容',['amazon-aplus-planner','amazon-visual-brief'],'以独立模块的视觉叙事、商品身份锁和整套风格锁规划A+；按需调研，不把A+做成重复海报。'),
 'batch_tryon':('批量换衣',['batch-production'],'原模板决定人物、场景和布局，当前逻辑服装决定商品事实；分层分析与样图审核，复用原B路径。'),
 'listing_images':('商品主副图',['amazon-aplus-planner','amazon-visual-brief'],'整套Listing沿用Amazon图片方案：按公司六类方向按需选择数量；每张独立Prompt，共享商品身份与整套风格，统一方案确认后并发生成。'),
 'free_creation':('自由生图',['image-creation'],'以用户创意为主，主动设计主体层级、场景、镜头和光线；有商品参考时保留其真实外观。'),
 'image_edit':('图片编辑',['image-creation'],'准确引用上传图或当前Output，只改变明确要求的部分，保留商品事实及非目标区域；形成版本而非覆盖。'),
}


class ModuleChange(StrictModel):
    module:ModuleCode
    expected_revision:int=Field(ge=0)


def describe(module='auto',revision=0):
    label,skills,guidance=MODULES[module]
    return {'module':module,'revision':revision,'label':label,'primary_skills':skills,'guidance':guidance}


async def read(db,conv):
    mid=str(uuid5(NAMESPACE_URL,conv.id+':creative-context'))
    row=await db.scalar(select(HermesMessage).where(HermesMessage.id==mid,HermesMessage.organization_id==conv.organization_id,
        HermesMessage.user_id==conv.user_id,HermesMessage.conversation_id==conv.id,HermesMessage.role=='creative_context'))
    return describe(row.metadata_json['module'],row.metadata_json['revision']) if row else describe()


async def change(db,conv,module,expected_revision=None):
    if conv.mode!='chat':raise AppError('agent.mode_mismatch','专业模式仅用于对话创作。',409)
    current=await read(db,conv)
    if expected_revision is not None and current['revision']!=expected_revision:
        raise AppError('agent.revision_conflict','专业模式已在另一窗口更新，请刷新后切换。',409)
    if current['module']==module:return current
    mid=str(uuid5(NAMESPACE_URL,conv.id+':creative-context'))
    row=await db.get(HermesMessage,mid)
    data={'module':module,'revision':current['revision']+1}
    if row:row.metadata_json=data
    else:db.add(HermesMessage(id=mid,conversation_id=conv.id,organization_id=conv.organization_id,user_id=conv.user_id,
        role='creative_context',content='对话专业模式',metadata_json=data,created_at=datetime.now(timezone.utc)))
    await db.flush()
    return describe(**data)

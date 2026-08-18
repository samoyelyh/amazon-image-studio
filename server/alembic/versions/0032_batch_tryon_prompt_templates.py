"""add batch try-on prompt template system

Revision ID: 0032_batch_prompt_templates
Revises: 0031_batch_style_ts_defaults
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "0032_batch_prompt_templates"
down_revision: str | None = "0031_batch_style_ts_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PURE_WHITE_ANALYSIS_PROMPT = """你是一名专业的电商服装换衣提示词生成助手。

当前输入：
图A = 纯白底商品展示模板
图B = 当前批次第一件服装参考图

你的任务不是生成图片，也不是解释图片内容。

你的任务是：
根据图A和图B，直接输出一段【可用于后续批量换衣的最终提示词】。

要求如下：

1. 图A负责识别和决定：
- 商品展示方式（正面 / 背面 / 正背组合）
- 商品数量
- 商品摆放位置
- 商品大小比例
- 构图
- 留白
- 裁切范围
- 阴影方式
- 白底风格

2. 图B负责识别和决定：
- 当前服装的真实颜色
- 配色关系
- 图案
- 文字
- 号码
- Logo
- 印花
- 正面设计
- 背面设计
- 领口结构
- 袖口结构
- 肩部细节
- 左右袖细节

3. 输出的最终换衣提示词必须满足：
- 严格保持图A原有的纯白底商品展示方式
- 严格保持图A中的商品数量、位置、大小、构图、留白和阴影关系
- 仅将图A中的原服装替换为图B对应的当前服装
- 图B是服装视觉内容的唯一事实来源
- 不得继承图A原服装的颜色、图案、文字、号码、Logo或其他商品内容
- 如果图A同时展示正面和背面，必须正确使用图B中的正面和背面，不得混淆
- 左右袖以穿着者自身左右为准，不得交换、镜像或复制单侧元素
- 保持纯白背景，不增加人物、场景、道具、装饰元素
- 不要根据服装颜色修改白底背景

4. 不要把图B第一件服装的具体内容写成“固定批次值”的解释性文字。
要直接输出一段给图片生成模型使用的换衣提示词。

5. 输出要求：
只输出【最终换衣提示词】本身，不要输出分析过程，不要输出分点解释，不要输出多余说明。"""


def upgrade() -> None:
    op.create_table(
        "batch_tryon_prompt_presets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("template_type", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("analysis_prompt_template", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_system_preset", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_batch_tryon_prompt_presets_scope",
        "batch_tryon_prompt_presets",
        ["organization_id", "owner_user_id", "enabled", "sort_order"],
    )
    op.create_table(
        "batch_tryon_template_prompts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_job_id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=120), nullable=False),
        sa.Column("template_type", sa.String(length=60), nullable=False),
        sa.Column("preset_id", sa.String(length=36), nullable=True),
        sa.Column("template_asset_id", sa.String(length=36), nullable=False),
        sa.Column("first_garment_asset_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_job_id", sa.String(length=36), nullable=True),
        sa.Column("analysis_prompt_used", sa.Text(), nullable=False),
        sa.Column("generated_final_prompt", sa.Text(), nullable=True),
        sa.Column("edited_final_prompt", sa.Text(), nullable=True),
        sa.Column("prompt_status", sa.String(length=20), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preset_id"], ["batch_tryon_prompt_presets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_garment_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["analysis_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_job_id", "template_id", name="uq_batch_tryon_template_prompt_workflow_template"),
    )
    op.create_index("ix_batch_tryon_template_prompts_org_workflow", "batch_tryon_template_prompts", ["organization_id", "workflow_job_id"])
    op.create_index("ix_batch_tryon_template_prompts_analysis_job", "batch_tryon_template_prompts", ["analysis_job_id"])

    now = datetime.now(timezone.utc)
    op.bulk_insert(sa.table(
        "batch_tryon_prompt_presets",
        sa.column("id", sa.String()), sa.column("organization_id", sa.String()), sa.column("owner_user_id", sa.String()),
        sa.column("scope", sa.String()), sa.column("template_type", sa.String()), sa.column("label", sa.String()),
        sa.column("analysis_prompt_template", sa.Text()), sa.column("enabled", sa.Boolean()),
        sa.column("sort_order", sa.Integer()), sa.column("is_system_preset", sa.Boolean()),
        sa.column("created_by", sa.String()), sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
    ), [{
        "id": str(uuid4()), "organization_id": None, "owner_user_id": None, "scope": "system",
        "template_type": "pure_white", "label": "纯白底图",
        "analysis_prompt_template": PURE_WHITE_ANALYSIS_PROMPT, "enabled": True, "sort_order": 10,
        "is_system_preset": True, "created_by": None, "updated_by": None, "created_at": now, "updated_at": now,
    }])

    connection = op.get_bind()
    bindings = sa.table(
        "operation_resource_pools",
        sa.column("id", sa.String()), sa.column("organization_id", sa.String()), sa.column("operation_code", sa.String()),
        sa.column("resource_pool_id", sa.String()), sa.column("required_capability", sa.String()),
        sa.column("enabled", sa.Boolean()), sa.column("priority", sa.Integer()), sa.column("created_by", sa.String()),
        sa.column("updated_by", sa.String()), sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    source_rows = connection.execute(sa.select(bindings).where(
        bindings.c.operation_code == "batch_tryon.style_analyze",
        bindings.c.required_capability == "text_generation",
    )).mappings().all()
    if source_rows:
        op.bulk_insert(bindings, [{
            **{key: row[key] for key in row.keys() if key != "id" and key != "operation_code"},
            "id": str(uuid4()), "operation_code": "batch_tryon.prompt_analyze", "created_at": now, "updated_at": now,
        } for row in source_rows])

    quota_rules = sa.table(
        "quota_rules",
        sa.column("id", sa.String()), sa.column("organization_id", sa.String()), sa.column("operation_code", sa.String()),
        sa.column("name", sa.String()), sa.column("base_cost", sa.BigInteger()), sa.column("model_multipliers", sa.JSON()),
        sa.column("quality_multipliers", sa.JSON()), sa.column("resolution_multipliers", sa.JSON()),
        sa.column("resource_pool_multipliers", sa.JSON()), sa.column("enabled", sa.Boolean()),
        sa.column("effective_from", sa.DateTime(timezone=True)), sa.column("effective_to", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.String()), sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(quota_rules, [{
        "id": str(uuid4()), "organization_id": None, "operation_code": "batch_tryon.prompt_analyze",
        "name": "批量套图提示词分析", "base_cost": 1, "model_multipliers": {},
        "quality_multipliers": {"standard": "1"}, "resolution_multipliers": {"text": "1"},
        "resource_pool_multipliers": {"platform": "1", "personal": "0"}, "enabled": True,
        "effective_from": datetime(2020, 1, 1, tzinfo=timezone.utc), "effective_to": None,
        "created_by": None, "updated_by": None, "created_at": now, "updated_at": now,
    }])


def downgrade() -> None:
    op.execute("DELETE FROM operation_resource_pools WHERE operation_code = 'batch_tryon.prompt_analyze'")
    op.execute("DELETE FROM quota_rules WHERE operation_code = 'batch_tryon.prompt_analyze'")
    op.drop_index("ix_batch_tryon_template_prompts_analysis_job", table_name="batch_tryon_template_prompts")
    op.drop_index("ix_batch_tryon_template_prompts_org_workflow", table_name="batch_tryon_template_prompts")
    op.drop_table("batch_tryon_template_prompts")
    op.drop_index("ix_batch_tryon_prompt_presets_scope", table_name="batch_tryon_prompt_presets")
    op.drop_table("batch_tryon_prompt_presets")

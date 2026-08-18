"""publish football jersey smart image variation configuration

Revision ID: 0028_football_variations
Revises: 0027_listing_group_timestamps
"""

from collections.abc import Sequence
from datetime import datetime, timezone
import copy
import json
import uuid

import sqlalchemy as sa
from alembic import op


revision: str = "0028_football_variations"
down_revision: str | None = "0027_listing_group_timestamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _decode(value: object, fallback: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value if value is not None else fallback


VARIATION_CONFIG = {
    "enabled": True,
    "max_total_images": 20,
    "quick_defaults": [
        {"type_code": "scene", "plan_codes": ["game_day_stadium", "training_field", "stadium_stands", "sports_street"], "count": 1},
        {"type_code": "model", "plan_codes": ["male_athlete", "female_athlete"], "count": 1},
    ],
    "types": [
        {
            "code": "scene", "name": "场景裂变", "enabled": True, "default_count": 1,
            "recommended_aspect_ratio": "4:5",
            "preserve_elements": ["产品颜色", "图案", "文字", "号码", "姓名", "领型", "袖型", "版型", "面料和结构细节"],
            "allowed_changes": ["背景环境", "时间和光线", "氛围", "人物动作", "构图和镜头距离"],
            "prompt_rule": "Vary the environment, time, lighting, atmosphere, pose and camera distance while preserving the exact jersey identity and every visible product detail.",
            "plans": [
                {"code": "game_day_stadium", "name": "比赛日球场", "enabled": True, "default_selected": True, "prompt_template": "Place the product in an authentic American football game-day stadium scene with energetic but commercially controlled lighting. Keep the jersey dominant and fully readable."},
                {"code": "training_field", "name": "训练场", "enabled": True, "default_selected": True, "prompt_template": "Create a realistic American football training-field scene with natural athletic activity and clean e-commerce composition."},
                {"code": "stadium_stands", "name": "球场看台", "enabled": True, "default_selected": True, "prompt_template": "Create a stadium-stands lifestyle scene with restrained crowd atmosphere and the exact jersey as the clear visual focus."},
                {"code": "sports_street", "name": "运动街头", "enabled": True, "default_selected": True, "prompt_template": "Create a contemporary sports-street lifestyle scene suitable for Amazon while keeping the jersey design exact and unobstructed."},
            ],
        },
        {
            "code": "model", "name": "模特裂变", "enabled": True, "default_count": 1,
            "recommended_aspect_ratio": "4:5",
            "preserve_elements": ["产品颜色", "图案", "文字", "号码", "姓名", "领口", "袖口", "版型", "面料和结构细节"],
            "allowed_changes": ["模特类型", "人物形象", "动作", "人物数量", "穿着场景", "镜头角度"],
            "prompt_rule": "Vary only the model casting, pose, people count, wearing context and camera angle. Preserve the exact garment design, fit cues and all visible graphics.",
            "plans": [
                {"code": "male_athlete", "name": "男性运动模特", "enabled": True, "default_selected": True, "prompt_template": "Show the exact jersey on a natural Western male sportswear model in a confident commercial athletic pose."},
                {"code": "female_athlete", "name": "女性运动模特", "enabled": True, "default_selected": True, "prompt_template": "Show the exact jersey on a natural Western female sportswear model with realistic fit and a confident commercial athletic pose."},
                {"code": "game_day_outfit", "name": "比赛日穿搭", "enabled": True, "default_selected": False, "prompt_template": "Create a complete game-day outfit around the exact jersey without covering, redesigning or changing its graphics."},
                {"code": "casual_sportswear", "name": "休闲运动穿搭", "enabled": True, "default_selected": False, "prompt_template": "Create a relaxed sportswear styling treatment while preserving the exact jersey as the hero product."},
            ],
        },
        {
            "code": "detail", "name": "细节裂变", "enabled": True, "default_count": 1,
            "recommended_aspect_ratio": "1:1",
            "preserve_elements": ["产品颜色", "文字", "号码", "姓名", "领口", "袖口", "印花", "面料纹理", "缝线和结构"],
            "allowed_changes": ["局部聚焦位置", "裁切范围", "展示方式", "背景", "构图"],
            "prompt_rule": "Create a truthful close-detail view. Change only the crop, focus area, presentation surface, background and composition; never invent texture or construction details.",
            "plans": [
                {"code": "neckline_cuff", "name": "领口与袖口", "enabled": True, "default_selected": True, "prompt_template": "Create a clean macro detail composition emphasizing the verified neckline and sleeve-cuff construction."},
                {"code": "number_print", "name": "号码与印花", "enabled": True, "default_selected": True, "prompt_template": "Create a crisp close-up of the verified numbers, name text and printed graphics without changing typography, color or placement."},
                {"code": "fabric_structure", "name": "面料与结构", "enabled": True, "default_selected": False, "prompt_template": "Create a truthful fabric-and-construction close-up using only details visible in the product references."},
            ],
        },
        {
            "code": "selling_point", "name": "卖点裂变", "enabled": True, "default_count": 1,
            "recommended_aspect_ratio": "1:1",
            "preserve_elements": ["产品本体", "颜色", "图案", "文字", "号码", "姓名", "Listing已确认事实"],
            "allowed_changes": ["卖点主题", "文案重点", "局部展示方式", "图文布局", "构图"],
            "prompt_rule": "Build the visual selling point only from confirmed product analysis and Listing evidence. Never add unsupported material, performance, licensing or functional claims.",
            "plans": [
                {"code": "design_fidelity", "name": "设计保真卖点", "enabled": True, "default_selected": True, "prompt_template": "Create a clean selling-point visual emphasizing the verified colors, graphics, numbers and silhouette. Use restrained factual labels only when supported by the confirmed Listing."},
                {"code": "wearing_scenarios", "name": "穿着场景卖点", "enabled": True, "default_selected": False, "prompt_template": "Create a factual scenario-led selling-point composition based only on wearing contexts supported by the confirmed Listing."},
            ],
        },
    ],
}


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("""
        SELECT s.id AS skill_id, s.default_published_version_id, s.version AS skill_version,
               v.version_number, v.analysis_config, v.listing_config, v.translation_config,
               v.image_prompt_config, v.a_plus_config, v.full_config_snapshot,
               v.created_by
        FROM product_categories c
        JOIN category_skills s ON s.id = c.default_skill_id
        JOIN category_skill_versions v ON v.id = s.default_published_version_id
        WHERE c.category_code = 'football_jersey'
        LIMIT 1
    """)).mappings().first()
    if not row:
        return
    # MySQL may persist the version insert even when a later statement in this
    # data migration fails. Reusing an already-created variation version keeps
    # container restart/retry safe and completes the default binding.
    existing_versions = bind.execute(sa.text("""
        SELECT id, version_number, image_prompt_config
        FROM category_skill_versions
        WHERE skill_id=:skill_id
        ORDER BY version_number DESC
    """), {"skill_id": row["skill_id"]}).mappings().all()
    for existing in existing_versions:
        existing_image_config = _decode(existing["image_prompt_config"], {})
        if isinstance(existing_image_config, dict) and existing_image_config.get("variation_config"):
            bind.execute(sa.text("""
                UPDATE category_skills
                SET default_published_version_id=:version_id, version=:version_number, status='published'
                WHERE id=:skill_id
            """), {
                "version_id": existing["id"],
                "version_number": existing["version_number"],
                "skill_id": row["skill_id"],
            })
            return
    image_config = copy.deepcopy(_decode(row["image_prompt_config"], {}))
    if not isinstance(image_config, dict) or image_config.get("variation_config"):
        return
    image_config["variation_config"] = copy.deepcopy(VARIATION_CONFIG)
    full = copy.deepcopy(_decode(row["full_config_snapshot"], {}))
    if not isinstance(full, dict):
        full = {}
    full["image_prompt_config"] = image_config
    new_id = str(uuid.uuid4())
    # The current default version is not guaranteed to be the highest version:
    # administrators may have created later drafts. Allocate after the actual
    # maximum to preserve the per-Skill unique version constraint.
    number = max(
        [int(existing["version_number"] or 0) for existing in existing_versions]
        or [int(row["version_number"] or 0)]
    ) + 1
    now = datetime.now(timezone.utc)
    insert = sa.text("""
        INSERT INTO category_skill_versions
        (id, skill_id, version_number, status, analysis_config, listing_config, translation_config,
         image_prompt_config, a_plus_config, full_config_snapshot, change_summary, source_version_id,
         published_by, published_at, created_by, created_at, updated_at)
        VALUES
        (:id, :skill_id, :version_number, 'published', :analysis_config, :listing_config, :translation_config,
         :image_prompt_config, :a_plus_config, :full_config_snapshot, :change_summary, :source_version_id,
         :published_by, :published_at, :created_by, :created_at, :updated_at)
    """).bindparams(
        sa.bindparam("analysis_config", type_=sa.JSON()), sa.bindparam("listing_config", type_=sa.JSON()),
        sa.bindparam("translation_config", type_=sa.JSON()), sa.bindparam("image_prompt_config", type_=sa.JSON()),
        sa.bindparam("a_plus_config", type_=sa.JSON()), sa.bindparam("full_config_snapshot", type_=sa.JSON()),
    )
    bind.execute(insert, {
        "id": new_id, "skill_id": row["skill_id"], "version_number": number,
        "analysis_config": _decode(row["analysis_config"], {}), "listing_config": _decode(row["listing_config"], {}),
        "translation_config": _decode(row["translation_config"], {}), "image_prompt_config": image_config,
        "a_plus_config": _decode(row["a_plus_config"], {}), "full_config_snapshot": full,
        "change_summary": "Add Skill-driven smart image variation types and plans",
        "source_version_id": row["default_published_version_id"], "published_by": row["created_by"],
        "published_at": now, "created_by": row["created_by"], "created_at": now, "updated_at": now,
    })
    bind.execute(sa.text("""
        UPDATE category_skills
        SET default_published_version_id=:version_id, version=:version_number, status='published'
        WHERE id=:skill_id
    """), {"version_id": new_id, "version_number": number, "skill_id": row["skill_id"]})


def downgrade() -> None:
    # Published Skill versions are immutable. Downgrade intentionally keeps the
    # version record to avoid invalidating Sessions that may already reference it.
    pass

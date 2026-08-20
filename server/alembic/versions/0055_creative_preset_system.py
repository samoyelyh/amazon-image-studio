"""add visual, theme and AI model preset system

Revision ID: 0055_creative_presets
Revises: 0054_attachment_materials
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "0055_creative_presets"
down_revision: str | None = "0054_attachment_materials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id(kind: str, code: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"amazon-image-studio:phase9:{kind}:{code}"))


VISUALS = [
    ("amazon_conversion", "亚马逊高转化电商", "商品突出 · 卖点清晰", ["conversion", "commerce"], ["commercial", "sports"], True,
     "你正在为 Amazon Listing 策划一整套商品附图。本次采用亚马逊高转化电商方向。商品始终是第一视觉主体；商品颜色、版型、领口、袖口、面料、印花、号码、Logo及定制内容严格依据PRODUCT参考图。人物、背景、装饰、礼盒和场景只能辅助理解商品，不得抢夺焦点。采用成熟、真实、明亮、自然的欧美商业摄影质感，避免过度艺术化和杂乱构图。不同模块承担不同信息任务，整套保持统一定位、摄影品质和商业气质，让消费者数秒内理解卖点。输出简短整套视觉方向、每个模块中文方案和可执行中文生图Prompt。"),
    ("modern_commercial", "现代品牌商业", "年轻 · 干净 · 时尚", ["modern", "brand"], ["commercial", "young"], False,
     "本次采用现代品牌商业摄影方向。使用现代空间、自然光、简洁背景和清晰层次；商品保持主要视觉地位。构图可有设计感但不能牺牲识别度，人物和道具年轻简洁。以商品自身颜色为视觉线索，不得重设计颜色、版型、印花、号码、Logo或细节。不同模块保持统一现代品牌气质，同时具备电商信息传达和品牌广告质感。"),
    ("minimal_product", "极简商品视觉", "少元素 · 大留白", ["minimal", "clean"], ["commercial", "premium"], False,
     "本次采用极简商品视觉方向。使用干净背景、适度留白和明确焦点，减少无实际作用的人物、道具和装饰。商品保持高占比，以自身配色为主要色彩来源。场景仅保留帮助理解用途的必要元素，避免复杂图形、大量文字和过度光效。商品真实性高于一切风格要求。"),
    ("brand_poster", "品牌广告海报", "强构图 · 强视觉", ["poster", "brand"], ["commercial", "premium"], False,
     "本次采用品牌广告海报方向。在保持商品真实性和Amazon可读性的同时提高视觉冲击。允许大胆构图、镜头、空间和光影，可增加人物互动与故事场景，但商品始终是核心。禁止为海报效果改变商品颜色、印花、号码、Logo、版型和定制内容。各模块创意不同但广告语言统一，结果仍须适合作为Listing附图。"),
    ("young_energy", "年轻活力", "年轻 · 运动 · 社交", ["young", "active"], ["young", "active", "sports"], False,
     "本次采用年轻活力方向。围绕年轻消费者、运动文化、朋友社交和轻松生活方式策划。人物自然自信并有轻微互动，可使用运动、观赛、聚会和城市户外环境。构图有动感但不能使商品变形或遮挡，光线明亮自然。商品必须清晰完整，颜色、号码、印花和结构保持真实。"),
    ("premium_brand", "高级品牌质感", "克制 · 高级 · 精致", ["premium", "quality"], ["premium", "commercial"], False,
     "本次采用高级品牌质感方向。强调面料、剪裁、光影、空间和商品细节；背景道具简洁高品质，避免廉价装饰、杂乱场景和过饱和色。人物自然有气质，光线有层次且商品细节清晰。商品真实性高于视觉表现，整套统一、克制、有品牌价值感。"),
    ("real_lifestyle", "真实生活方式", "真实自然 · 使用代入", ["lifestyle", "natural"], ["lifestyle", "natural"], False,
     "本次采用真实生活方式方向。使用可信的家庭、朋友、户外、城市、观赛或休闲环境，人物动作互动自然，光线接近日常摄影。商品清晰可识别，场景有生活气息但不杂乱。颜色、版型、号码、印花和定制内容严格保持，让消费者理解何时穿、和谁穿及真实体验。"),
    ("game_day_fan", "比赛日球迷", "体育赛事 · 观赛氛围", ["football", "fan", "sports"], ["fan", "sports", "active"], False,
     "本次采用比赛日球迷文化方向。围绕比赛日、观赛、朋友聚会和球迷身份表达策划，优先家庭观赛、朋友聚会、体育酒吧氛围、球场周边和城市比赛日。商品是身份表达核心，强调穿着效果、号码和定制内容。人物自然互动但不抢主体，避免未经授权的真实球队Logo和品牌元素，严格保持商品真实性。"),
    ("gift_emotion", "礼品情感", "定制专属 · 赠礼价值", ["gift", "emotion"], ["natural", "lifestyle"], False,
     "本次采用个性化礼品情感方向。强化姓名、号码、定制内容的专属感、纪念意义和赠礼价值，可使用生日、家庭、情侣、朋友、节日和拆礼物场景。礼盒、丝带、卡片只作辅助，不得遮挡商品关键内容。整体温暖精致真实，商品始终是礼物场景核心。"),
    ("professional_sports", "专业运动品牌", "专业 · 运动 · 功能感", ["sports", "professional"], ["sports", "active"], False,
     "本次采用专业运动品牌方向。使用球场、训练区域、更衣室和运动设施，人物自然有力量感。突出商品版型、面料、剪裁和活动自由度，细节模块表现领口、袖口、网眼、印花和结构。避免夸张动作导致衣服变形，构图清晰利落，商品设计严格真实。"),
]

THEMES = [
    ("independence_day", "美国独立日", "7月4日 · 夏日庆祝", ["holiday", "usa"],
     "在当前视觉模板基础上加入美国独立日/7月4日主题。可使用美国夏季节日、红白蓝环境色彩、星条元素、家庭聚会、后院派对、BBQ、城市节庆和户外庆祝，但商品真实颜色、号码、印花、Logo和定制内容不能改变。主题只属于环境和氛围，不覆盖商品；避免过量国旗元素，并按模块控制主题强度。"),
    ("christmas", "圣诞节", "冬季节日 · 温暖赠礼", ["holiday", "gift"],
     "在当前视觉模板基础上加入圣诞节赠礼与冬季节日氛围。可使用圣诞树、暖色灯光、礼物、家庭聚会、冬季室内和红绿金辅助元素。商品颜色、号码、印花、Logo和设计保持完全真实，装饰不得改变、遮挡或抢夺商品主体。"),
    ("fathers_day", "父亲节", "家庭感谢 · 男性赠礼", ["gift", "family"], "加入父亲节家庭感谢与赠礼氛围，突出定制与纪念价值；所有主题元素只辅助场景，商品外观和定制内容必须保持真实。"),
    ("mothers_day", "母亲节", "温暖家庭 · 感谢赠礼", ["gift", "family"], "加入母亲节温暖家庭与感谢赠礼氛围，保持真实自然和克制装饰；不得改变商品颜色、结构、印花和定制信息。"),
    ("birthday_gift", "生日礼物", "生日庆祝 · 个性定制", ["gift", "birthday"], "加入生日庆祝与个性化礼物氛围，可使用礼盒、蛋糕和聚会线索，但商品始终是主体且外观与定制信息保持真实。"),
    ("valentines_day", "情人节", "情侣赠礼 · 情感连接", ["gift", "romance"], "加入克制、真实的情人节情侣赠礼氛围，避免过度浪漫装饰；商品设计、颜色和定制内容不可改变。"),
    ("back_to_school", "返校季", "校园活力 · 新学期", ["school", "young"], "加入返校季、新学期和校园活力氛围，场景服务于商品用途理解，不得引入未经确认的学校或球队标识。"),
    ("football_season", "比赛日 / Football Season", "赛季 · 球迷文化", ["football", "sports"], "加入Football Season比赛日、观赛聚会与球迷文化氛围，避免真实球队和联盟授权元素，严格保持商品本身颜色、号码、图案和定制内容。"),
]

MODELS = [
    ("M01", "阳光运动男模", "Mason", "male", "25–30", "自然运动型", "阳光、自信、亲和的运动生活方式男模", ["sports", "active", "fan", "young"]),
    ("M02", "专业运动男模", "Ethan", "male", "25–32", "专业运动型", "力量感自然的专业运动男模", ["sports", "professional", "active"]),
    ("M03", "年轻街头男模", "Noah", "male", "20–27", "修长自然型", "年轻现代的街头生活方式男模", ["young", "street", "lifestyle"]),
    ("M04", "成熟生活男模", "Liam", "male", "35–45", "自然成熟型", "真实可靠的成熟生活方式男模", ["mature", "natural", "lifestyle"]),
    ("M05", "高级商业男模", "James", "male", "28–38", "匀称商业型", "克制精致的高级商业男模", ["premium", "commercial"]),
    ("M06", "自然球迷男模", "Logan", "male", "25–38", "普通自然型", "真实有代入感的自然球迷男模", ["fan", "natural", "sports"]),
    ("F01", "年轻活力女模", "Sophia", "female", "20–28", "自然活力型", "年轻、自信、自然的活力女模", ["young", "active", "lifestyle"]),
    ("F02", "专业运动女模", "Ava", "female", "24–32", "专业运动型", "专业可靠的运动商业女模", ["sports", "professional", "active"]),
    ("F03", "时尚街头女模", "Mia", "female", "20–29", "修长自然型", "现代时尚的街头生活方式女模", ["street", "young", "commercial"]),
    ("F04", "真实生活女模", "Emma", "female", "28–40", "普通自然型", "亲和真实的生活方式女模", ["natural", "lifestyle"]),
    ("F05", "高级商业女模", "Olivia", "female", "28–38", "匀称商业型", "克制精致的高级商业女模", ["premium", "commercial"]),
    ("F06", "自然球迷女模", "Harper", "female", "24–36", "自然运动型", "真实自然的球迷生活方式女模", ["fan", "natural", "sports"]),
]


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    op.create_table("visual_presets",
        sa.Column("organization_id", sa.String(36), nullable=True), sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("short_description", sa.String(500), nullable=False),
        sa.Column("category_scope", sa.JSON(), nullable=False), sa.Column("recommended_modules", sa.JSON(), nullable=False),
        sa.Column("recommended_model_tags", sa.JSON(), nullable=False), sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True), sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True), sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "code", name="uq_visual_presets_scope_code"))
    op.create_index("ix_visual_presets_active_order", "visual_presets", ["organization_id", "is_active", "sort_order"])
    op.create_table("visual_preset_versions",
        sa.Column("preset_id", sa.String(36), nullable=False), sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("full_prompt_template", sa.Text(), nullable=False), sa.Column("change_summary", sa.String(500), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True), sa.ForeignKeyConstraint(["preset_id"], ["visual_presets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("preset_id", "version_number", name="uq_visual_preset_version_number"))
    op.create_index("ix_visual_preset_versions_preset", "visual_preset_versions", ["preset_id", "version_number"])
    op.create_foreign_key("fk_visual_presets_current_version", "visual_presets", "visual_preset_versions", ["current_version_id"], ["id"], ondelete="SET NULL")

    op.create_table("theme_presets",
        sa.Column("organization_id", sa.String(36), nullable=True), sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("short_description", sa.String(500), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False), sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True), sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "code", name="uq_theme_presets_scope_code"))
    op.create_index("ix_theme_presets_active_order", "theme_presets", ["organization_id", "is_active", "sort_order"])
    op.create_table("theme_preset_versions",
        sa.Column("preset_id", sa.String(36), nullable=False), sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("full_prompt_template", sa.Text(), nullable=False), sa.Column("change_summary", sa.String(500), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True), sa.ForeignKeyConstraint(["preset_id"], ["theme_presets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("preset_id", "version_number", name="uq_theme_preset_version_number"))
    op.create_foreign_key("fk_theme_presets_current_version", "theme_presets", "theme_preset_versions", ["current_version_id"], ["id"], ondelete="SET NULL")

    op.create_table("ai_model_presets",
        sa.Column("organization_id", sa.String(36), nullable=True), sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("gender_presentation", sa.String(40), nullable=False), sa.Column("age_range", sa.String(60), nullable=False),
        sa.Column("body_type", sa.String(120), nullable=False), sa.Column("short_description", sa.String(500), nullable=False),
        sa.Column("identity_prompt", sa.Text(), nullable=False), sa.Column("generation_prompt", sa.Text(), nullable=False),
        sa.Column("negative_constraints", sa.Text(), nullable=False), sa.Column("recommended_visual_presets", sa.JSON(), nullable=False),
        sa.Column("recommended_modules", sa.JSON(), nullable=False), sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("cover_asset_id", sa.String(36), nullable=True), sa.Column("current_identity_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True), sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cover_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "code", name="uq_ai_model_presets_scope_code"))
    op.create_index("ix_ai_model_presets_status_order", "ai_model_presets", ["organization_id", "status", "sort_order"])
    op.create_table("ai_model_identity_versions",
        sa.Column("organization_id", sa.String(36), nullable=True), sa.Column("model_preset_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False), sa.Column("status", sa.String(30), nullable=False),
        sa.Column("identity_prompt_snapshot", sa.Text(), nullable=False), sa.Column("identity_asset_id", sa.String(36), nullable=True),
        sa.Column("identity_job_id", sa.String(36), nullable=True), sa.Column("reference_batch_id", sa.String(36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True), sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_preset_id"], ["ai_model_presets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["identity_asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["identity_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reference_batch_id"], ["job_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("model_preset_id", "version_number", name="uq_ai_model_identity_version_number"))
    op.create_index("ix_ai_model_identity_versions_preset", "ai_model_identity_versions", ["model_preset_id", "version_number"])
    op.create_foreign_key("fk_ai_model_presets_current_identity", "ai_model_presets", "ai_model_identity_versions", ["current_identity_version_id"], ["id"], ondelete="SET NULL")
    op.create_table("ai_model_preset_references",
        sa.Column("organization_id", sa.String(36), nullable=True), sa.Column("model_preset_id", sa.String(36), nullable=False),
        sa.Column("identity_version_id", sa.String(36), nullable=False), sa.Column("reference_role", sa.String(40), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False), sa.Column("source_job_id", sa.String(36), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False), sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True), sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_preset_id"], ["ai_model_presets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["identity_version_id"], ["ai_model_identity_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("identity_version_id", "reference_role", name="uq_ai_model_reference_role"))
    op.create_index("ix_ai_model_references_asset", "ai_model_preset_references", ["asset_id"])
    op.create_table("attachment_plan_model_selections",
        sa.Column("organization_id", sa.String(36), nullable=False), sa.Column("workbench_plan_id", sa.String(36), nullable=False),
        sa.Column("product_slot", sa.Integer(), nullable=False), sa.Column("model_preset_id", sa.String(36), nullable=False),
        sa.Column("identity_version_id", sa.String(36), nullable=False), sa.Column("source", sa.String(30), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workbench_plan_id"], ["attachment_workbench_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_preset_id"], ["ai_model_presets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["identity_version_id"], ["ai_model_identity_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workbench_plan_id", "product_slot", name="uq_attachment_plan_model_slot"))
    op.create_index("ix_attachment_plan_models_plan", "attachment_plan_model_selections", ["workbench_plan_id", "product_slot"])

    for name, type_, nullable, default in (
        ("visual_preset_id", sa.String(36), True, None), ("visual_preset_version_id", sa.String(36), True, None),
        ("theme_preset_id", sa.String(36), True, None), ("theme_preset_version_id", sa.String(36), True, None),
        ("model_selection_mode", sa.String(30), False, sa.text("'recommended'")),
        ("creative_context_version", sa.Integer(), False, sa.text("0")),
    ):
        op.add_column("attachment_workbench_plans", sa.Column(name, type_, nullable=nullable, server_default=default))
    op.create_foreign_key("fk_attachment_plan_visual_preset", "attachment_workbench_plans", "visual_presets", ["visual_preset_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_attachment_plan_visual_version", "attachment_workbench_plans", "visual_preset_versions", ["visual_preset_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_attachment_plan_theme_preset", "attachment_workbench_plans", "theme_presets", ["theme_preset_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_attachment_plan_theme_version", "attachment_workbench_plans", "theme_preset_versions", ["theme_preset_version_id"], ["id"], ondelete="SET NULL")
    for name in (
        "visual_preset_id", "visual_preset_version_id", "theme_preset_id", "theme_preset_version_id",
    ):
        op.add_column("attachment_workbench_plan_versions", sa.Column(name, sa.String(36), nullable=True))
    # MySQL does not allow defaults on TEXT/JSON columns. Add them nullable,
    # backfill historical plan versions, then enforce the ORM's non-null invariant.
    op.add_column("attachment_workbench_plan_versions", sa.Column("visual_preset_prompt_snapshot", sa.Text(), nullable=True))
    op.add_column("attachment_workbench_plan_versions", sa.Column("theme_prompt_snapshot", sa.Text(), nullable=True))
    op.add_column("attachment_workbench_plan_versions", sa.Column("selected_model_snapshot", sa.JSON(), nullable=True))
    op.execute(sa.text(
        "UPDATE attachment_workbench_plan_versions "
        "SET visual_preset_prompt_snapshot='', theme_prompt_snapshot='', selected_model_snapshot='[]' "
        "WHERE visual_preset_prompt_snapshot IS NULL "
        "OR theme_prompt_snapshot IS NULL OR selected_model_snapshot IS NULL"
    ))
    op.alter_column(
        "attachment_workbench_plan_versions", "visual_preset_prompt_snapshot",
        existing_type=sa.Text(), nullable=False,
    )
    op.alter_column(
        "attachment_workbench_plan_versions", "theme_prompt_snapshot",
        existing_type=sa.Text(), nullable=False,
    )
    op.alter_column(
        "attachment_workbench_plan_versions", "selected_model_snapshot",
        existing_type=sa.JSON(), nullable=False,
    )
    op.create_foreign_key("fk_attachment_version_visual_preset", "attachment_workbench_plan_versions", "visual_presets", ["visual_preset_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_attachment_version_visual_version", "attachment_workbench_plan_versions", "visual_preset_versions", ["visual_preset_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_attachment_version_theme_preset", "attachment_workbench_plan_versions", "theme_presets", ["theme_preset_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_attachment_version_theme_version", "attachment_workbench_plan_versions", "theme_preset_versions", ["theme_preset_version_id"], ["id"], ondelete="SET NULL")

    visual_table = sa.table(
        "visual_presets",
        sa.column("id", sa.String()), sa.column("organization_id", sa.String()), sa.column("code", sa.String()),
        sa.column("name", sa.String()), sa.column("short_description", sa.String()),
        sa.column("category_scope", sa.JSON()), sa.column("recommended_modules", sa.JSON()),
        sa.column("recommended_model_tags", sa.JSON()), sa.column("tags", sa.JSON()),
        sa.column("current_version_id", sa.String()), sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()), sa.column("is_default", sa.Boolean()),
        sa.column("created_by", sa.String()), sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    visual_version_table = sa.table(
        "visual_preset_versions", sa.column("id", sa.String()), sa.column("preset_id", sa.String()),
        sa.column("version_number", sa.Integer()), sa.column("full_prompt_template", sa.Text()),
        sa.column("change_summary", sa.String()), sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for order, (code, name, desc, tags, model_tags, default, prompt) in enumerate(VISUALS, 10):
        pid, vid = _id("visual", code), _id("visual-version", code)
        op.bulk_insert(visual_table, [{"id":pid,"organization_id":None,"code":code,"name":name,"short_description":desc,"category_scope":[],"recommended_modules":[],"recommended_model_tags":model_tags,"tags":tags,"current_version_id":None,"sort_order":order,"is_active":True,"is_default":default,"created_by":None,"updated_by":None,"created_at":now,"updated_at":now}])
        op.bulk_insert(visual_version_table, [{"id":vid,"preset_id":pid,"version_number":1,"full_prompt_template":prompt,"change_summary":"Phase 9 系统初始化","created_by":None,"created_at":now}])
        op.execute(sa.text("UPDATE visual_presets SET current_version_id=:v WHERE id=:p").bindparams(v=vid,p=pid))
    theme_table = sa.table(
        "theme_presets", sa.column("id", sa.String()), sa.column("organization_id", sa.String()),
        sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("short_description", sa.String()),
        sa.column("tags", sa.JSON()), sa.column("current_version_id", sa.String()),
        sa.column("sort_order", sa.Integer()), sa.column("is_active", sa.Boolean()),
        sa.column("created_by", sa.String()), sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    theme_version_table = sa.table(
        "theme_preset_versions", sa.column("id", sa.String()), sa.column("preset_id", sa.String()),
        sa.column("version_number", sa.Integer()), sa.column("full_prompt_template", sa.Text()),
        sa.column("change_summary", sa.String()), sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for order, (code, name, desc, tags, prompt) in enumerate(THEMES, 10):
        pid, vid = _id("theme", code), _id("theme-version", code)
        op.bulk_insert(theme_table, [{"id":pid,"organization_id":None,"code":code,"name":name,"short_description":desc,"tags":tags,"current_version_id":None,"sort_order":order,"is_active":True,"created_by":None,"updated_by":None,"created_at":now,"updated_at":now}])
        op.bulk_insert(theme_version_table, [{"id":vid,"preset_id":pid,"version_number":1,"full_prompt_template":prompt,"change_summary":"Phase 9 系统初始化","created_by":None,"created_at":now}])
        op.execute(sa.text("UPDATE theme_presets SET current_version_id=:v WHERE id=:p").bindparams(v=vid,p=pid))
    model_table = sa.table(
        "ai_model_presets", sa.column("id", sa.String()), sa.column("organization_id", sa.String()),
        sa.column("code", sa.String()), sa.column("name", sa.String()), sa.column("display_name", sa.String()),
        sa.column("gender_presentation", sa.String()), sa.column("age_range", sa.String()),
        sa.column("body_type", sa.String()), sa.column("short_description", sa.String()),
        sa.column("identity_prompt", sa.Text()), sa.column("generation_prompt", sa.Text()),
        sa.column("negative_constraints", sa.Text()), sa.column("recommended_visual_presets", sa.JSON()),
        sa.column("recommended_modules", sa.JSON()), sa.column("tags", sa.JSON()),
        sa.column("cover_asset_id", sa.String()), sa.column("current_identity_version_id", sa.String()),
        sa.column("status", sa.String()), sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()), sa.column("is_published", sa.Boolean()),
        sa.column("created_by", sa.String()), sa.column("updated_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    base_generation = "Create one reusable adult AI commercial model identity in a clean neutral studio with soft commercial lighting. Dress the model in plain neutral unbranded clothing with no logos, graphics, numbers or text. Prioritize clear facial identity, natural anatomy, realistic skin, consistent hairstyle and reusable commercial appearance. Avoid celebrity resemblance, exaggerated retouching, dramatic styling, unusual accessories, branded clothing, text, logos and distorted anatomy."
    for order, (code, name, display, gender, age, body, desc, tags) in enumerate(MODELS, 10):
        identity = f"Adult {gender} commercial lifestyle model, apparent age {age}, {body}. {desc}. Maintain exactly the same facial identity, hairstyle, body proportions and apparent age across future images."
        op.bulk_insert(model_table, [{"id":_id("model",code),"organization_id":None,"code":code,"name":name,"display_name":display,"gender_presentation":gender,"age_range":age,"body_type":body,"short_description":desc,"identity_prompt":identity,"generation_prompt":base_generation,"negative_constraints":"Ignore and never preserve clothing from MODEL references in product generation.","recommended_visual_presets":[],"recommended_modules":["stadium_scene","gift_scene","casual_scene"],"tags":tags,"cover_asset_id":None,"current_identity_version_id":None,"status":"DRAFT","sort_order":order,"is_active":True,"is_published":False,"created_by":None,"updated_by":None,"created_at":now,"updated_at":now}])


def downgrade() -> None:
    for name, table in (
        ("fk_attachment_version_theme_version", "attachment_workbench_plan_versions"),
        ("fk_attachment_version_theme_preset", "attachment_workbench_plan_versions"),
        ("fk_attachment_version_visual_version", "attachment_workbench_plan_versions"),
        ("fk_attachment_version_visual_preset", "attachment_workbench_plan_versions"),
        ("fk_attachment_plan_theme_version", "attachment_workbench_plans"),
        ("fk_attachment_plan_theme_preset", "attachment_workbench_plans"),
        ("fk_attachment_plan_visual_version", "attachment_workbench_plans"),
        ("fk_attachment_plan_visual_preset", "attachment_workbench_plans"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")
    for table, names in (("attachment_workbench_plan_versions", ["selected_model_snapshot","theme_prompt_snapshot","theme_preset_version_id","theme_preset_id","visual_preset_prompt_snapshot","visual_preset_version_id","visual_preset_id"]), ("attachment_workbench_plans", ["creative_context_version","model_selection_mode","theme_preset_version_id","theme_preset_id","visual_preset_version_id","visual_preset_id"])):
        for name in names:
            op.drop_column(table, name)
    op.drop_table("attachment_plan_model_selections")
    op.drop_constraint("fk_ai_model_presets_current_identity", "ai_model_presets", type_="foreignkey")
    op.drop_table("ai_model_preset_references"); op.drop_table("ai_model_identity_versions"); op.drop_table("ai_model_presets")
    op.drop_constraint("fk_theme_presets_current_version", "theme_presets", type_="foreignkey")
    op.drop_table("theme_preset_versions"); op.drop_table("theme_presets")
    op.drop_constraint("fk_visual_presets_current_version", "visual_presets", type_="foreignkey")
    op.drop_table("visual_preset_versions"); op.drop_table("visual_presets")

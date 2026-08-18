from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class ProductCategory(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_categories"
    __table_args__ = (
        UniqueConstraint("category_code", name="uq_product_categories_code"),
        Index("ix_product_categories_active_sort", "is_active", "sort_order"),
    )

    category_code: Mapped[str] = mapped_column(String(100), nullable=False)
    category_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    default_skill_id: Mapped[str | None] = mapped_column(
        ForeignKey("category_skills.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    default_listing_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    default_image_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("category_image_templates.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class CategorySkill(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "category_skills"
    __table_args__ = (
        UniqueConstraint("category_id", "skill_code", "version", name="uq_category_skills_version"),
        Index("ix_category_skills_category_active", "category_id", "is_active"),
    )

    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id", ondelete="CASCADE"), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(160), nullable=False)
    skill_code: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    analysis_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    listing_title_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    bullet_points_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    a_plus_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    image_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    image_types_config: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list, nullable=False)
    prompt_rules: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    marketplace: Mapped[str] = mapped_column(String(40), default="amazon_us", nullable=False)
    language: Mapped[str] = mapped_column(String(40), default="en-US_zh-CN", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    default_published_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("category_skill_versions.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class CategoryImageTemplate(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "category_image_templates"
    __table_args__ = (
        UniqueConstraint("category_id", "template_code", "version", name="uq_category_image_templates_version"),
        Index("ix_category_image_templates_category_active", "category_id", "is_active"),
    )

    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id", ondelete="CASCADE"), nullable=False)
    template_name: Mapped[str] = mapped_column(String(160), nullable=False)
    template_code: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    image_type_prompts: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    default_image_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ProductAnalysisResult(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_analysis_results"
    __table_args__ = (Index("ix_product_analysis_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("category_skills.id", ondelete="RESTRICT"), nullable=False)
    source_asset_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    structured_attributes: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    listing_content: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class ListingGenerationSession(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "listing_generation_sessions"
    __table_args__ = (
        Index("ix_listing_sessions_org_created", "organization_id", "created_at"),
        Index("ix_listing_sessions_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("category_skills.id", ondelete="RESTRICT"), nullable=False)
    skill_version_id: Mapped[str | None] = mapped_column(ForeignKey("category_skill_versions.id", ondelete="SET NULL"), nullable=True)
    category_skill_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    analysis_result_id: Mapped[str | None] = mapped_column(
        ForeignKey("product_analysis_results.id", ondelete="SET NULL"), nullable=True
    )
    planning_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    image_batch_id: Mapped[str | None] = mapped_column(ForeignKey("job_batches.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="analyzing", nullable=False)
    source_asset_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    primary_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    listing_content: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    current_listing_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("listing_versions.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class ListingVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "listing_versions"
    __table_args__ = (
        UniqueConstraint("session_id", "version_number", name="uq_listing_versions_session_number"),
        Index("ix_listing_versions_org_session", "organization_id", "session_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_listing_version_id: Mapped[str | None] = mapped_column(ForeignKey("listing_versions.id", ondelete="SET NULL"), nullable=True)
    listing_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    analysis_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    category_skill_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class ListingImageProject(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "listing_image_projects"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_listing_image_projects_session"),
        Index("ix_listing_image_projects_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=False)
    listing_version_id: Mapped[str] = mapped_column(ForeignKey("listing_versions.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="editing", nullable=False)
    selected_template: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generated_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_batch_id: Mapped[str | None] = mapped_column(ForeignKey("job_batches.id", ondelete="SET NULL"), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class ListingImageTaskGroup(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "listing_image_task_groups"
    __table_args__ = (
        UniqueConstraint("listing_image_project_id", "group_number", name="uq_listing_image_task_groups_number"),
        UniqueConstraint("job_batch_id", name="uq_listing_image_task_groups_batch"),
        Index("ix_listing_image_task_groups_org_project", "organization_id", "listing_image_project_id", "created_at"),
        Index("ix_listing_image_task_groups_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    listing_image_project_id: Mapped[str] = mapped_column(ForeignKey("listing_image_projects.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=False)
    listing_version_id: Mapped[str] = mapped_column(ForeignKey("listing_versions.id", ondelete="RESTRICT"), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False)
    category_skill_version_id: Mapped[str | None] = mapped_column(ForeignKey("category_skill_versions.id", ondelete="SET NULL"), nullable=True)
    job_batch_id: Mapped[str | None] = mapped_column(ForeignKey("job_batches.id", ondelete="SET NULL"), nullable=True)
    source_task_group_id: Mapped[str | None] = mapped_column(
        ForeignKey("listing_image_task_groups.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    group_number: Mapped[int] = mapped_column(Integer, nullable=False)
    group_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    product_image_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    reference_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    template_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    input_asset_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    selected_image_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class APlusProject(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "a_plus_projects"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_a_plus_projects_session"),
        Index("ix_a_plus_projects_org_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=False)
    listing_version_id: Mapped[str] = mapped_column(ForeignKey("listing_versions.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="editing", nullable=False)
    selected_template: Mapped[str | None] = mapped_column(String(120), nullable=True)
    modules: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list, nullable=False)
    prompt_config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generated_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_batch_id: Mapped[str | None] = mapped_column(ForeignKey("job_batches.id", ondelete="SET NULL"), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class PromptDebugConfig(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_debug_configs"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_prompt_debug_session"),
        Index("ix_prompt_debug_org_session", "organization_id", "session_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False)
    skill_id: Mapped[str] = mapped_column(ForeignKey("category_skills.id", ondelete="RESTRICT"), nullable=False)
    system_prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    skill_prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_prompt_segment: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    final_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    final_prompts: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class ImagePromptItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "image_prompt_items"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "project_type", "project_id", "item_code",
            name="uq_image_prompt_items_project_code",
        ),
        Index("ix_image_prompt_items_project", "organization_id", "project_type", "project_id"),
        Index("ix_image_prompt_items_status", "organization_id", "status"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    project_type: Mapped[str] = mapped_column(String(40), nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True)
    skill_id: Mapped[str | None] = mapped_column(ForeignKey("category_skills.id", ondelete="SET NULL"), nullable=True)
    item_code: Mapped[str] = mapped_column(String(120), nullable=False)
    image_type: Mapped[str] = mapped_column(String(120), nullable=False)
    original_english_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    chinese_editing_instruction: Mapped[str] = mapped_column(Text, default="", nullable=False)
    optimized_english_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    optimizer_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    optimizer_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    optimized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class ImagePromptVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "image_prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_item_id", "version_number", name="uq_image_prompt_versions_item_number"),
        UniqueConstraint("optimizer_job_id", name="uq_image_prompt_versions_optimizer_job"),
        Index("ix_image_prompt_versions_item", "prompt_item_id", "version_number"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    prompt_item_id: Mapped[str] = mapped_column(ForeignKey("image_prompt_items.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_english_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    chinese_editing_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    optimized_english_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    optimizer_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    optimizer_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    optimized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    optimized_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class CategorySkillVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "category_skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_category_skill_versions_number"),
        Index("ix_category_skill_versions_skill_status", "skill_id", "status"),
    )

    skill_id: Mapped[str] = mapped_column(ForeignKey("category_skills.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    analysis_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    listing_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    translation_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    image_prompt_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    a_plus_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    full_config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    change_summary: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    source_version_id: Mapped[str | None] = mapped_column(ForeignKey("category_skill_versions.id", ondelete="SET NULL"), nullable=True)
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

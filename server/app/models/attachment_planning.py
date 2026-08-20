from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UuidPrimaryKeyMixin


class AttachmentWorkbenchPlan(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_workbench_plans"
    __table_args__ = (
        UniqueConstraint("listing_image_project_id", name="uq_attachment_workbench_plan_project"),
        Index("ix_attachment_workbench_plans_org_project", "organization_id", "listing_image_project_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    listing_image_project_id: Mapped[str] = mapped_column(ForeignKey("listing_image_projects.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("listing_generation_sessions.id", ondelete="CASCADE"), nullable=False)
    listing_version_id: Mapped[str] = mapped_column(ForeignKey("listing_versions.id", ondelete="RESTRICT"), nullable=False)
    skill_version_id: Mapped[str | None] = mapped_column(ForeignKey("category_skill_versions.id", ondelete="SET NULL"), nullable=True)
    visual_direction_cn: Mapped[str] = mapped_column(Text, default="", nullable=False)
    visual_direction_source: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    visual_direction_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    planning_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    planning_status: Mapped[str] = mapped_column(String(30), default="idle", nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class AttachmentWorkbenchModulePlan(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_workbench_module_plans"
    __table_args__ = (
        UniqueConstraint("workbench_plan_id", "module_key", name="uq_attachment_module_plan_key"),
        Index("ix_attachment_module_plans_org_plan", "organization_id", "workbench_plan_id"),
        Index("ix_attachment_module_plans_derived_output", "derived_from_output_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    workbench_plan_id: Mapped[str] = mapped_column(ForeignKey("attachment_workbench_plans.id", ondelete="CASCADE"), nullable=False)
    module_key: Mapped[str] = mapped_column(String(60), nullable=False)
    plan_summary_cn: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prompt_cn: Mapped[str] = mapped_column(Text, default="", nullable=False)
    operator_requirement_cn: Mapped[str] = mapped_column(Text, default="", nullable=False)
    aspect_ratio: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    derived_from_output_id: Mapped[str | None] = mapped_column(
        ForeignKey("generated_outputs.id", ondelete="SET NULL"), nullable=True,
    )
    current_version_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    planning_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reference_context_dirty: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reference_state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference_analysis_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class AttachmentModuleResultState(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_module_result_states"
    __table_args__ = (
        UniqueConstraint("listing_image_project_id", "module_key", name="uq_attachment_result_state_project_module"),
        Index("ix_attachment_result_states_org_project", "organization_id", "listing_image_project_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    listing_image_project_id: Mapped[str] = mapped_column(ForeignKey("listing_image_projects.id", ondelete="CASCADE"), nullable=False)
    module_key: Mapped[str] = mapped_column(String(60), nullable=False)
    current_final_output_id: Mapped[str | None] = mapped_column(
        ForeignKey("generated_outputs.id", ondelete="SET NULL"), nullable=True,
    )
    results_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class AttachmentWorkbenchPlanVersion(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_workbench_plan_versions"
    __table_args__ = (
        UniqueConstraint("workbench_plan_id", "version_scope", "version_number", name="uq_attachment_plan_version_scope"),
        Index("ix_attachment_plan_versions_org_plan", "organization_id", "workbench_plan_id", "created_at"),
        Index("ix_attachment_plan_versions_creative", "organization_id", "module_plan_id", "generation_mode", "created_at"),
        Index("ix_attachment_plan_versions_derived_output", "derived_from_output_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    workbench_plan_id: Mapped[str] = mapped_column(ForeignKey("attachment_workbench_plans.id", ondelete="CASCADE"), nullable=False)
    module_plan_id: Mapped[str | None] = mapped_column(ForeignKey("attachment_workbench_module_plans.id", ondelete="CASCADE"), nullable=True)
    version_scope: Mapped[str] = mapped_column(String(80), nullable=False)
    module_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(20), default="standard", nullable=False)
    creative_direction_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    derived_from_output_id: Mapped[str | None] = mapped_column(
        ForeignKey("generated_outputs.id", ondelete="SET NULL"), nullable=True,
    )
    visual_direction_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_summary_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_cn: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_requirement_cn: Mapped[str] = mapped_column(Text, default="", nullable=False)
    aspect_ratio: Mapped[str | None] = mapped_column(String(20), nullable=True)
    selected_module_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    skill_version_id: Mapped[str | None] = mapped_column(ForeignKey("category_skill_versions.id", ondelete="SET NULL"), nullable=True)
    skill_rule_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    source_version_id: Mapped[str | None] = mapped_column(ForeignKey("attachment_workbench_plan_versions.id", ondelete="SET NULL"), nullable=True)
    ai_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reference_understanding_id: Mapped[str | None] = mapped_column(
        ForeignKey("attachment_reference_understandings.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class AttachmentProductReferenceGroup(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_product_reference_groups"
    __table_args__ = (
        UniqueConstraint("workbench_plan_id", name="uq_attachment_product_group_plan"),
        Index("ix_attachment_product_groups_org_plan", "organization_id", "workbench_plan_id"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    workbench_plan_id: Mapped[str] = mapped_column(ForeignKey("attachment_workbench_plans.id", ondelete="CASCADE"), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class AttachmentProductReferenceItem(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_product_reference_items"
    __table_args__ = (
        UniqueConstraint("product_group_id", "asset_id", "view_role", name="uq_attachment_product_item_role"),
        Index("ix_attachment_product_items_org_group", "organization_id", "product_group_id", "sort_order"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    product_group_id: Mapped[str] = mapped_column(ForeignKey("attachment_product_reference_groups.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    view_role: Mapped[str] = mapped_column(String(20), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="session", nullable=False)
    transform_metadata: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class AttachmentModuleReference(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_module_references"
    __table_args__ = (
        UniqueConstraint("module_plan_id", "slot_type", "asset_id", name="uq_attachment_module_reference_asset"),
        Index("ix_attachment_module_refs_org_module", "organization_id", "module_plan_id", "slot_type", "sort_order"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    module_plan_id: Mapped[str] = mapped_column(ForeignKey("attachment_workbench_module_plans.id", ondelete="CASCADE"), nullable=False)
    slot_type: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class AttachmentReferenceUnderstanding(UuidPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "attachment_reference_understandings"
    __table_args__ = (
        UniqueConstraint("module_plan_id", "version_number", name="uq_attachment_understanding_version"),
        Index("ix_attachment_understandings_org_module", "organization_id", "module_plan_id", "version_number"),
    )

    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    module_plan_id: Mapped[str] = mapped_column(ForeignKey("attachment_workbench_module_plans.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="analyzing", nullable=False)
    structured_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    source_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    ai_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

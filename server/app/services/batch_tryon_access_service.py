"""Private batch inputs and outputs remain owner-only, including direct ID access."""
from sqlalchemy import select
from app.core.errors import AppError
from app.models.content import Asset, Project, ProjectAsset

BATCH_PRIVATE_ASSET_CATEGORIES = {"batch_tryon_output", "model_template", "garment", "garment_reference"}


def batch_asset_link_exists(asset_id):
    return select(ProjectAsset.id).join(Project, Project.id == ProjectAsset.project_id).where(
        ProjectAsset.asset_id == asset_id, Project.project_type == "batch_tryon",
    ).exists()


async def is_private_batch_asset(session, asset):
    seen = set()
    while asset and asset.id not in seen:
        seen.add(asset.id)
        from app.services.agent_access_service import agent_output_exists
        if (asset.metadata_json or {}).get("private_scope") == "agent_chat" or await session.scalar(select(agent_output_exists(asset.id))):
            return True
        if asset.category in BATCH_PRIVATE_ASSET_CATEGORIES - {"model_template"}:
            return True
        # Preserve explicit administrator publication of shared reference inputs.
        # Private output/garment categories above are never made public by a link.
        # Public TEMPLATE uploads already use model_template in the existing UI.
        from app.models.attachment_planning import AttachmentReferenceLibraryItem
        published = await session.scalar(select(AttachmentReferenceLibraryItem.id).where(
            AttachmentReferenceLibraryItem.asset_id == asset.id,
            AttachmentReferenceLibraryItem.organization_id == asset.organization_id,
            AttachmentReferenceLibraryItem.is_active.is_(True),
        ).limit(1))
        if published:
            return False
        if asset.category == "model_template" or await session.scalar(select(batch_asset_link_exists(asset.id))):
            return True
        asset = await session.get(Asset, asset.source_asset_id) if asset.source_asset_id else None
    return False


async def require_batch_asset_access(session, *, organization_id, user_id, asset_ids):
    ids = {str(value) for value in asset_ids if value}
    if not ids:
        return
    rows = (await session.scalars(select(Asset).where(
        Asset.id.in_(ids), Asset.organization_id == organization_id, Asset.deleted_at.is_(None),
    ))).all()
    if len(rows) != len(ids):
        raise AppError("asset.not_found", "部分素材不存在或不属于当前账号。", 404)
    for asset in rows:
        if asset.created_by != user_id and await is_private_batch_asset(session, asset):
            raise AppError("asset.not_found", "部分素材不存在或不属于当前账号。", 404)

from __future__ import annotations

import io
import zipfile

from sqlalchemy import func, select

import pytest

from app.core.errors import AppError
from app.models.attachment_material import (
    AttachmentMaterialItem,
    AttachmentMaterialSet,
    AttachmentMaterialSetVersion,
)
from app.models.content import Asset, GeneratedOutput
from app.models.identity import User
from app.models.listing_workflow import ListingImageProject
from app.models.tasks import Job
from app.services.asset_service import delete_asset
from app.services.attachment_material_service import (
    archive_material_set,
    build_material_zip,
    get_material_set,
    list_material_sets,
    material_items,
    material_versions,
    save_project_material_set,
    save_single_output,
)
from app.services.attachment_result_service import discard_attachment_results, set_attachment_final
from tests.test_attachment_output_review import _seed_outputs


async def _save(
    context,
    *,
    project_id: str,
    user_id: str,
    material_set_id: str | None = None,
    save_mode: str = "update",
):
    async with context["session_factory"]() as db:
        result = await save_project_material_set(
            db,
            organization_id=context["first_org"],
            project_id=project_id,
            display_name="测试球衣 Listing 套图",
            tags=["橄榄球衣", "Listing套图"],
            note="Phase 8 test",
            material_set_id=material_set_id,
            save_mode=save_mode,
            user_id=user_id,
        )
        await db.commit()
        return result.material_set.id, result.version.version_number, result.created_version, result.unchanged


@pytest.mark.asyncio
async def test_save_set_is_idempotent_and_creates_immutable_versions(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        await db.commit()

    set_id, version_number, created, unchanged = await _save(
        identity_test_context, project_id=project_id, user_id=user_id,
    )
    assert (version_number, created, unchanged) == (1, True, False)

    repeated = await _save(
        identity_test_context, project_id=project_id, user_id=user_id, material_set_id=set_id,
    )
    assert repeated[1:] == (1, False, True)

    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        await set_attachment_final(db, project=project, output_id=output_ids[1], user_id=user_id)
        await db.commit()

    updated = await _save(
        identity_test_context, project_id=project_id, user_id=user_id, material_set_id=set_id,
    )
    assert updated[1:] == (2, True, False)

    async with identity_test_context["session_factory"]() as db:
        versions = await material_versions(db, material_set_id=set_id)
        assert [row.version_number for row in versions] == [2, 1]
        v2_items = await material_items(db, version_id=versions[0].id)
        v1_items = await material_items(db, version_id=versions[1].id)
        assert v1_items[0].source_output_id == output_ids[0]
        assert v2_items[0].source_output_id == output_ids[1]
        assert v1_items[0].source_asset_id == v2_items[0].source_asset_id


@pytest.mark.asyncio
async def test_completeness_uses_selected_module_snapshot(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        project.prompt_config = {"attachment_workbench": {"modules": {
            "pure_white": {"selected": True},
            "gift_scene": {"selected": True},
        }}}
        await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        await db.commit()

    set_id, _, _, _ = await _save(identity_test_context, project_id=project_id, user_id=user_id)
    async with identity_test_context["session_factory"]() as db:
        material_set = await db.get(AttachmentMaterialSet, set_id)
        version = await db.get(AttachmentMaterialSetVersion, material_set.current_version_id)
        assert version.selected_module_snapshot == ["pure_white", "gift_scene"]
        assert version.module_count == 1
        assert version.target_module_count == 2
        assert version.is_complete is False
        assert material_set.is_complete is False


@pytest.mark.asyncio
async def test_single_save_uses_same_set_version_item_structure(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        result = await save_single_output(
            db,
            organization_id=identity_test_context["first_org"],
            project_id=project_id,
            output_id=output_ids[0],
            display_name="单张礼品场景",
            tags=["礼品场景"],
            note="",
            material_set_id=None,
            save_mode="new",
            user_id=user_id,
        )
        await db.commit()
        assert result.version.version_number == 1
        assert result.version.is_complete is True
        assert result.version.selected_module_snapshot == ["gift_scene"]
        items = await material_items(db, version_id=result.version.id)
        assert len(items) == 1
        assert items[0].module_key == "gift_scene"
        assert items[0].source_output_id == output_ids[0]


@pytest.mark.asyncio
async def test_material_remains_after_workbench_results_are_cleared(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        await db.commit()

    set_id, _, _, _ = await _save(identity_test_context, project_id=project_id, user_id=user_id)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        await discard_attachment_results(db, project=project, module_keys=["gift_scene"], user_id=user_id)
        material_set = await db.get(AttachmentMaterialSet, set_id)
        version = await db.get(AttachmentMaterialSetVersion, material_set.current_version_id)
        items = await material_items(db, version_id=version.id)
        output = await db.get(GeneratedOutput, items[0].source_output_id)
        assert output is not None
        assert items[0].source_asset_id == output.asset_id


@pytest.mark.asyncio
async def test_personal_scope_and_archive_filter(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        await db.commit()

    set_id, _, _, _ = await _save(identity_test_context, project_id=project_id, user_id=user_id)
    async with identity_test_context["session_factory"]() as db:
        other_user = await db.scalar(select(User).where(User.account == "first-viewer"))
        with pytest.raises(AppError) as error:
            await get_material_set(
                db,
                organization_id=identity_test_context["first_org"],
                material_set_id=set_id,
                owner_user_id=other_user.id,
            )
        assert error.value.status_code == 404

        material_set = await get_material_set(
            db,
            organization_id=identity_test_context["first_org"],
            material_set_id=set_id,
            owner_user_id=user_id,
        )
        await archive_material_set(db, material_set=material_set, user_id=user_id)
        rows, total = await list_material_sets(
            db,
            organization_id=identity_test_context["first_org"],
            owner_user_id=user_id,
            search=None,
            category_key=None,
            completion=None,
            include_archived=False,
            organization_scope=False,
            limit=20,
            offset=0,
        )
        assert total == 0 and rows == []
        archived_rows, archived_total = await list_material_sets(
            db,
            organization_id=identity_test_context["first_org"],
            owner_user_id=user_id,
            search=None,
            category_key=None,
            completion=None,
            include_archived=True,
            organization_scope=False,
            limit=20,
            offset=0,
        )
        assert archived_total == 1 and archived_rows[0].id == set_id
        assert await db.scalar(select(func.count()).select_from(AttachmentMaterialItem)) == 1


@pytest.mark.asyncio
async def test_material_scope_enforces_organization_and_owner(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        await db.commit()
    set_id, _, _, _ = await _save(identity_test_context, project_id=project_id, user_id=user_id)

    async with identity_test_context["session_factory"]() as db:
        with pytest.raises(AppError) as error:
            await get_material_set(
                db,
                organization_id=identity_test_context["second_org"],
                material_set_id=set_id,
                owner_user_id=user_id,
            )
        assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_lineage_preserves_multi_product_and_creative_mode(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        output = await db.get(GeneratedOutput, output_ids[0])
        job = await db.get(Job, output.job_id)
        payload = dict(job.input_json)
        metadata = dict(payload.get("metadata") or {})
        metadata.update({"generation_mode": "creative", "product_mode": "MULTI"})
        payload["metadata"] = metadata
        job.input_json = payload
        result = await save_single_output(
            db,
            organization_id=identity_test_context["first_org"],
            project_id=project_id,
            output_id=output_ids[0],
            display_name="多商品创意图",
            tags=["MULTI", "CREATIVE"],
            note="",
            material_set_id=None,
            save_mode="new",
            user_id=user_id,
        )
        await db.commit()
        item = (await material_items(db, version_id=result.version.id))[0]
        assert item.product_mode == "MULTI"
        assert item.generation_mode == "CREATIVE"
        assert item.source_job_id == job.id
        assert item.source_task_group_id is not None
        assert item.plan_version_id is not None
        assert item.prompt_version_id is not None
        assert item.reference_understanding_id is not None


@pytest.mark.asyncio
async def test_material_asset_reference_blocks_physical_delete(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        result = await save_single_output(
            db,
            organization_id=identity_test_context["first_org"],
            project_id=project_id,
            output_id=output_ids[0],
            display_name="删除保护",
            tags=[],
            note="",
            material_set_id=None,
            save_mode="new",
            user_id=user_id,
        )
        orphan = Asset(
            organization_id=identity_test_context["first_org"],
            category="listing_output",
            storage_key="tests/material-only.png",
            filename="material-only.png",
            mime_type="image/png",
            size=8,
            width=10,
            height=10,
            sha256="9" * 64,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(orphan)
        await db.flush()
        item = (await material_items(db, version_id=result.version.id))[0]
        item.source_output_id = None
        item.source_asset_id = orphan.id
        await db.flush()
        identity_test_context["storage"].upload(orphan.storage_key, b"material", content_type="image/png")
        with pytest.raises(AppError) as error:
            await delete_asset(
                db,
                identity_test_context["storage"],
                organization_id=identity_test_context["first_org"],
                asset_id=orphan.id,
                user_id=user_id,
            )
        assert error.value.code == "asset.in_use"


@pytest.mark.asyncio
async def test_zip_is_temporary_and_uses_business_module_filename(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        result = await save_single_output(
            db,
            organization_id=identity_test_context["first_org"],
            project_id=project_id,
            output_id=output_ids[0],
            display_name="礼品场景 ZIP",
            tags=[],
            note="",
            material_set_id=None,
            save_mode="new",
            user_id=user_id,
        )
        item = (await material_items(db, version_id=result.version.id))[0]
        asset = await db.get(Asset, item.source_asset_id)
        content = b"phase-8-image-bytes"
        identity_test_context["storage"].upload(asset.storage_key, content, content_type=asset.mime_type)
        archive_bytes = await build_material_zip(db, identity_test_context["storage"], version=result.version)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assert archive.namelist() == ["04_gift_scene.png"]
            assert archive.read("04_gift_scene.png") == content
        assert not any(key.endswith(".zip") for key in identity_test_context["storage"].objects)


@pytest.mark.asyncio
async def test_material_api_save_list_detail_and_owner_isolation(identity_test_context) -> None:
    _, user_id, project_id, _, output_ids = await _seed_outputs(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        await set_attachment_final(db, project=project, output_id=output_ids[0], user_id=user_id)
        await db.commit()

    client = identity_test_context["client"]
    login = await client.post("/api/v1/auth/login", json={"account": "first-admin", "password": "correct-password"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    context = await client.get(f"/api/v1/attachment-materials/projects/{project_id}/save-context", headers=headers)
    assert context.status_code == 200
    assert context.json()["default_name"]
    saved = await client.post(
        f"/api/v1/attachment-materials/projects/{project_id}/save",
        headers=headers,
        json={"display_name": "API 套图", "tags": ["Listing"], "note": "API test", "save_mode": "new"},
    )
    assert saved.status_code == 200
    material_set_id = saved.json()["material_set"]["id"]
    assert saved.json()["material_set"]["current_version_number"] == 1
    mine = await client.get("/api/v1/attachment-materials", headers=headers)
    assert mine.status_code == 200
    assert [item["id"] for item in mine.json()["items"]] == [material_set_id]
    detail = await client.get(f"/api/v1/attachment-materials/{material_set_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["versions"][0]["items"][0]["module_key"] == "gift_scene"

    viewer_login = await client.post("/api/v1/auth/login", json={"account": "first-viewer", "password": "viewer-password"})
    viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
    hidden = await client.get(f"/api/v1/attachment-materials/{material_set_id}", headers=viewer_headers)
    assert hidden.status_code == 404

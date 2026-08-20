from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.content import Asset
from app.models.identity import User
from app.models.listing_workflow import ListingGenerationSession, ListingImageProject
from tests.test_attachment_references import _project_with_assets


async def _secondary_session(context: dict[str, object], project_id: str, suffix: str, *, other_org: bool = False) -> str:
    async with context["session_factory"]() as db:
        project = await db.get(ListingImageProject, project_id)
        source = await db.get(ListingGenerationSession, project.session_id)
        account = "second-admin" if other_org else "first-admin"
        user = await db.scalar(select(User).where(User.account == account))
        organization_id = context["second_org"] if other_org else context["first_org"]
        asset = Asset(
            organization_id=organization_id, category="product_reference",
            storage_key=f"tests/attachment/composition-{suffix}.png",
            filename=f"composition-{suffix}.png", mime_type="image/png",
            size=128, width=100, height=100, sha256=(suffix * 64)[:64],
            created_by=user.id, updated_by=user.id,
        )
        db.add(asset)
        await db.flush()
        session = ListingGenerationSession(
            organization_id=organization_id, category_id=source.category_id, skill_id=source.skill_id,
            category_skill_snapshot=dict(source.category_skill_snapshot or {}), status="confirmed",
            primary_asset_id=asset.id, source_asset_ids=[asset.id],
            listing_content={"title": {"zh": f"附加商品{suffix}"}},
            confirmed_at=datetime.now(timezone.utc), confirmed_by=user.id,
            created_by=user.id, updated_by=user.id,
        )
        db.add(session)
        await db.commit()
        return session.id


@pytest.mark.asyncio
async def test_product_composition_is_versioned_restorable_limited_and_org_isolated(identity_test_context) -> None:
    project_id, _ = await _project_with_assets(identity_test_context)
    session_b = await _secondary_session(identity_test_context, project_id, "b")
    session_c = await _secondary_session(identity_test_context, project_id, "c")
    session_d = await _secondary_session(identity_test_context, project_id, "d")
    foreign_session = await _secondary_session(identity_test_context, project_id, "x", other_org=True)
    client = identity_test_context["client"]
    login = await client.post("/api/v1/auth/login", json={"account": "first-admin", "password": "correct-password"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    planning = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/planning", headers=headers)
    assert planning.status_code == 200, planning.text
    support = {item["module_key"]: item["supports_multi_product"] for item in planning.json()["modules"]}
    assert support == {
        "pure_white": False, "custom_process": False, "stadium_scene": True,
        "gift_scene": True, "detail_display": False, "casual_scene": True,
    }
    initial = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/product-compositions", headers=headers)
    assert initial.status_code == 200, initial.text
    assert len(initial.json()) == 6
    stadium = next(item for item in initial.json() if item["module_key"] == "stadium_scene")
    assert stadium["mode"] == "SINGLE"
    assert [item["product_role"] for item in stadium["products"]] == ["PRIMARY"]

    unsupported = next(item for item in initial.json() if item["module_key"] == "pure_white")
    blocked = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/pure_white/product-composition",
        headers=headers, json={"mode": "MULTI", "expected_state_version": unsupported["state_version"]},
    )
    assert blocked.status_code == 422

    switched = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/stadium_scene/product-composition",
        headers=headers, json={"mode": "MULTI", "expected_state_version": stadium["state_version"]},
    )
    assert switched.status_code == 200, switched.text
    stadium = switched.json()
    assert stadium["current_version_number"] > 1

    foreign = await client.post(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/stadium_scene/product-composition/products",
        headers=headers, json={"source_session_id": foreign_session, "expected_state_version": stadium["state_version"]},
    )
    assert foreign.status_code == 404

    added_b = await client.post(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/stadium_scene/product-composition/products",
        headers=headers, json={"source_session_id": session_b, "expected_state_version": stadium["state_version"]},
    )
    assert added_b.status_code == 200, added_b.text
    stadium = added_b.json()
    assert len(stadium["products"]) == 2
    duplicate = await client.post(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/stadium_scene/product-composition/products",
        headers=headers, json={"source_session_id": session_b, "expected_state_version": stadium["state_version"]},
    )
    assert duplicate.status_code == 422

    added_c = await client.post(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/stadium_scene/product-composition/products",
        headers=headers, json={"source_session_id": session_c, "expected_state_version": stadium["state_version"]},
    )
    assert added_c.status_code == 200, added_c.text
    stadium = added_c.json()
    assert len(stadium["products"]) == 3
    limited = await client.post(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/stadium_scene/product-composition/products",
        headers=headers, json={"source_session_id": session_d, "expected_state_version": stadium["state_version"]},
    )
    assert limited.status_code == 422

    single = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/stadium_scene/product-composition",
        headers=headers, json={"mode": "SINGLE", "expected_state_version": stadium["state_version"]},
    )
    assert single.status_code == 200, single.text
    assert single.json()["mode"] == "SINGLE"
    assert len(single.json()["products"]) == 3
    restored = await client.patch(
        f"/api/v1/attachment-workbench/projects/{project_id}/modules/stadium_scene/product-composition",
        headers=headers, json={"mode": "MULTI", "expected_state_version": single.json()["state_version"]},
    )
    assert restored.status_code == 200, restored.text
    assert [item["source_session_id"] for item in restored.json()["products"]][1:] == [session_b, session_c]

    refreshed = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/product-compositions", headers=headers)
    recovered = next(item for item in refreshed.json() if item["module_key"] == "stadium_scene")
    assert recovered["mode"] == "MULTI"
    assert len(recovered["products"]) == 3
    planning_after = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/planning", headers=headers)
    stadium_plan = next(item for item in planning_after.json()["modules"] if item["module_key"] == "stadium_scene")
    assert stadium_plan["reference_context_dirty"] is True
    assert stadium_plan["status"] in {"draft", "stale"}

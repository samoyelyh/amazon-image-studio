import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.models.quota import QuotaReservation, QuotaRule
from app.models.tasks import (
    BatchTryOnPromptPreset, BatchTryOnTemplatePrompt, Job, JobStatus, ModelCapability,
    OperationResourcePool, Provider, ProviderModel, ResourcePool, ResourcePoolKey,
)
from app.services.batch_tryon_prompt_service import (
    append_manual_retry_constraints,
    build_batch_try_on_prompt,
    build_template_prompt_composed_prompt,
)
from app.services.batch_tryon_workflow_service import (
    continue_batch_tryon_workflow,
    submit_confirmed_batch_tryon_workflow,
)
from app.services.batch_tryon_prompt_template_service import validate_generated_final_prompt
from app.prompts.batch_tryon_prompt_templates import SYSTEM_PROMPT_PRESETS
from app.services.batch_tryon_analysis_service import (
    normalize_garment_profile,
    validate_garment_profile,
)
from app.services.resource_pool_service import create_api_key


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
    "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)


def test_short_generated_final_prompt_is_allowed() -> None:
    assert validate_generated_final_prompt("只换衣服") == "只换衣服"


def test_generated_final_prompt_strips_outer_markdown_fence() -> None:
    value = "```text\n请严格保留图A构图，仅替换为图B当前服装。\n```"
    assert validate_generated_final_prompt(value) == "请严格保留图A构图，仅替换为图B当前服装。"


def test_analysis_only_response_is_still_rejected() -> None:
    with pytest.raises(AppError) as error:
        validate_generated_final_prompt("分析过程：先识别图A，再识别图B。")
    assert error.value.code == "batch_tryon.prompt_analysis_invalid"


async def auth_headers(client) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={
        "email": "first-admin@example.com", "password": "correct-password",
    })
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def upload(client, headers, category: str, filename: str) -> dict:
    response = await client.post(
        "/api/v1/assets", headers=headers, data={"category": category},
        files={"file": (filename, PNG, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def seed_workflow_resources(context) -> None:
    settings = Settings(_env_file=None)
    async with context["session_factory"]() as session:
        provider = Provider(
            code="workflow-provider", name="Workflow provider", provider_type="openai_compatible",
            base_url="https://relay.example/v1", config_json={},
        )
        session.add(provider)
        await session.flush()
        text_model = ProviderModel(
            provider_id=provider.id, code="workflow-text", upstream_model="text-model",
            name="Workflow text", config_json={},
        )
        image_model = ProviderModel(
            provider_id=provider.id, code="workflow-image", upstream_model="image-model",
            name="Workflow image", config_json={},
        )
        luna_model = ProviderModel(
            provider_id=provider.id, code="gpt-5.6-luna", upstream_model="gpt-5.6-luna",
            name="Workflow Luna", config_json={},
        )
        session.add_all([text_model, luna_model, image_model])
        await session.flush()
        session.add_all([
            ModelCapability(model_id=text_model.id, capability="text_generation"),
            ModelCapability(model_id=text_model.id, capability="vision_input"),
            ModelCapability(model_id=luna_model.id, capability="text_generation"),
            ModelCapability(model_id=luna_model.id, capability="vision_input"),
            ModelCapability(model_id=image_model.id, capability="image_edit"),
        ])
        text_pool = ResourcePool(model_id=text_model.id, code="workflow-text-pool", name="Workflow text pool")
        image_pool = ResourcePool(model_id=image_model.id, code="workflow-image-pool", name="Workflow image pool")
        luna_pool = ResourcePool(model_id=luna_model.id, code="workflow-luna-pool", name="Workflow Luna pool")
        session.add_all([text_pool, luna_pool, image_pool])
        await session.flush()
        session.add_all([
            OperationResourcePool(
                operation_code="batch_tryon.style_analyze", resource_pool_id=text_pool.id,
                required_capability="text_generation", priority=100,
            ),
            OperationResourcePool(
                operation_code="batch_tryon.prompt_analyze", resource_pool_id=text_pool.id,
                required_capability="text_generation", priority=100,
            ),
            OperationResourcePool(
                operation_code="batch_tryon.prompt_analyze_detailed", resource_pool_id=luna_pool.id,
                required_capability="text_generation", priority=100,
            ),
            OperationResourcePool(
                operation_code="batch_tryon.generate", resource_pool_id=image_pool.id,
                required_capability="image_edit", priority=100,
            ),
        ])
        key = create_api_key(
            settings, provider_id=provider.id, label="Workflow key", secret="workflow-secret-key",
            organization_id=None, max_concurrency=10, rpm_limit=None, daily_limit=None, user_id=None,
        )
        session.add(key)
        await session.flush()
        session.add_all([
            ResourcePoolKey(resource_pool_id=text_pool.id, api_key_id=key.id),
            ResourcePoolKey(resource_pool_id=luna_pool.id, api_key_id=key.id),
            ResourcePoolKey(resource_pool_id=image_pool.id, api_key_id=key.id),
            QuotaRule(
                organization_id=None,
                operation_code="batch_tryon.style_analyze",
                name="Batch try-on analysis",
                base_cost=1,
                model_multipliers={}, quality_multipliers={}, resolution_multipliers={},
                resource_pool_multipliers={"platform": "1"},
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
            QuotaRule(
                organization_id=None,
                operation_code="batch_tryon.prompt_analyze_detailed",
                name="Batch try-on detailed prompt analysis",
                base_cost=1,
                model_multipliers={}, quality_multipliers={"detailed": "1"}, resolution_multipliers={},
                resource_pool_multipliers={"platform": "1"},
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
            QuotaRule(
                organization_id=None,
                operation_code="batch_tryon.prompt_analyze",
                name="Batch try-on prompt analysis",
                base_cost=1,
                model_multipliers={}, quality_multipliers={}, resolution_multipliers={},
                resource_pool_multipliers={"platform": "1"},
                effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
            *[
                BatchTryOnPromptPreset(
                    organization_id=None, owner_user_id=None, scope="system",
                    template_type=template_type, label=label,
                    analysis_prompt_template=analysis_prompt,
                    enabled=True, sort_order=sort_order, is_system_preset=True,
                )
                for template_type, label, analysis_prompt, sort_order in SYSTEM_PROMPT_PRESETS
            ],
        ])
        await session.commit()


def test_prompt_builder_separates_business_delivery_and_manual_retry() -> None:
    prompt = build_batch_try_on_prompt(
        mode="detail_tryon",
        garment_filename="06-shirt.png",
        template_name="neckline-detail.png",
        garment_profile={"garment_structure": {"neckline": "v-neck"}},
        template_profile={"focus_area": "neckline", "crop_type": "detail"},
    )
    assert "sole visual truth" in prompt.business_prompt
    assert "DETAIL TRY-ON" in prompt.business_prompt
    assert "Preserve the template crop" in prompt.business_prompt
    assert prompt.technical_delivery_contract == ""
    retried = append_manual_retry_constraints(
        prompt.business_prompt, error_codes=["left_right_sleeve", "text_number"],
    )
    assert "REVIEW CORRECTION REQUIREMENTS:" in retried
    assert "wearer-left" in retried
    assert "leading zeros" in retried


def test_pure_white_composer_does_not_inherit_model_try_on_constraints() -> None:
    prompt = build_template_prompt_composed_prompt(
        template_type="pure_white",
        reusable_final_prompt="Preserve the white product layout and replace its garment from the current garment reference.",
        garment_filename="06-shirt.png",
        template_name="front-back-layout.png",
    )
    assert "PURE WHITE PRODUCT LAYOUT" in prompt.effective_prompt
    assert "sole visual source" in prompt.effective_prompt
    assert "current garment" in prompt.effective_prompt.lower()
    assert "model identity" not in prompt.effective_prompt.lower()
    assert "face" not in prompt.effective_prompt.lower()
    assert "pose" not in prompt.effective_prompt.lower()


def test_each_template_type_has_distinct_real_composer_constraints() -> None:
    expectations = {
        "pure_white": ("PURE WHITE PRODUCT LAYOUT", "pure white background"),
        "gift_scene": ("GIFT SCENE", "gift props"),
        "stadium_scene": ("STADIUM SPECTATOR SCENE", "crowd distribution"),
        "detail_display": ("GARMENT DETAIL DISPLAY", "detail focus area"),
        "casual_scene": ("CASUAL LIFESTYLE SCENE", "trousers, shoes, accessories"),
        "custom_process": ("CUSTOMIZATION PROCESS INFOGRAPHIC", "process copy exactly"),
    }
    prompts = {}
    for template_type, (heading, constraint) in expectations.items():
        prompt = build_template_prompt_composed_prompt(
            template_type=template_type,
            reusable_final_prompt=None,
            garment_filename="current-shirt.png",
            template_name=f"{template_type}.png",
        ).effective_prompt
        prompts[template_type] = prompt
        assert heading in prompt
        assert constraint in prompt
        assert "CURRENT-GARMENT OVERRIDE" in prompt
    assert len(set(prompts.values())) == len(expectations)

    with_font = build_template_prompt_composed_prompt(
        template_type="pure_white",
        reusable_final_prompt=None,
        garment_filename="current-shirt.png",
        template_name="white-layout.png",
        has_font_reference=True,
    ).effective_prompt
    assert "REFERENCE IMAGE 3 — CUSTOM TYPOGRAPHY ONLY" in with_font
    assert "must never override Reference Image 2" in with_font

    front_back = build_template_prompt_composed_prompt(
        template_type="custom_process", reusable_final_prompt=None,
        garment_filename="current-shirt.png", template_name="process.png",
        garment_reference_count=2, has_font_reference=True,
    ).effective_prompt
    assert "Reference Image 2 is the clean front garment reference" in front_back
    assert "Reference Image 4 is the clean back garment reference" in front_back
    assert "REFERENCE IMAGE 3 — CUSTOM TYPOGRAPHY ONLY" in front_back


def test_legacy_nested_garment_analysis_recovers_concrete_structure() -> None:
    profile = normalize_garment_profile({
        "garment_type": "cropped athletic jersey",
        "reusable_structure_rules": {
            "silhouette": {"fit": "boxy relaxed", "hem": "straight cropped hem"},
            "neckline": {"type": "deep V-neck", "front_opening": "pullover"},
            "sleeves": {"type": "loose short sleeves"},
        },
    }, source_asset_id="asset-1", model_code="vision-model")
    validate_garment_profile(profile)
    assert profile["category"] == "cropped athletic jersey"
    assert profile["garment_structure"] == {
        "neckline": "deep V-neck",
        "sleeve_type": "loose short sleeves",
        "fit": "boxy relaxed",
        "closure": "pullover",
        "hem_type": "straight cropped hem",
    }

    top_level_profile = normalize_garment_profile({
        "garment_type": "football jersey",
        "silhouette": {"fit": "relaxed", "hem": "straight"},
        "neckline": {"type": "V-neck", "front_opening": "pullover"},
        "sleeves": {"type": "short sleeves"},
    }, source_asset_id="asset-2", model_code="vision-model")
    validate_garment_profile(top_level_profile)
    assert top_level_profile["garment_structure"]["neckline"] == "V-neck"
    assert top_level_profile["garment_structure"]["sleeve_type"] == "short sleeves"


async def test_server_workflow_uses_entered_presets_directly_without_ai_and_builds_matrix(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    await seed_workflow_resources(identity_test_context)
    headers = await auth_headers(client)
    project_response = await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "Workflow project", "draft": {},
    })
    project_id = project_response.json()["id"]
    templates = [
        await upload(client, headers, "model_template", "front.png"),
        await upload(client, headers, "model_template", "detail.png"),
    ]
    garments = [
        await upload(client, headers, "garment", "01-shirt.png"),
        await upload(client, headers, "garment", "02-shirt.png"),
    ]
    default_font = await upload(client, headers, "style_reference", "01-font.png")
    combination_font = await upload(client, headers, "style_reference", "01-font-special.png")
    created = await client.post("/api/v1/batch-tryon/workflows", headers=headers, json={
        "project_id": project_id,
        "name": "Server workflow",
        "idempotency_key": "workflow-create-001",
        "generation_mode": "normal_tryon",
        "prompt_mode": "direct",
        "templates": [
            {
                "template_id": f"template-{index}", "asset_id": asset["id"],
                "name": asset["filename"], "order": index,
                "template_type": "pure_white" if index == 0 else "gift_scene",
            }
            for index, asset in enumerate(templates)
        ],
        "garments": [
            {
                "garment_id": f"garment-{index}", "asset_id": asset["id"],
                "filename": asset["filename"], "order": index,
                "font_reference_asset_id": default_font["id"] if index == 0 else None,
            }
            for index, asset in enumerate(garments)
        ],
        "combinations": [
            {
                "client_item_id": f"item-{t}-{g}", "template_id": f"template-{t}",
                "garment_id": f"garment-{g}", "order": t * 2 + g,
                "font_reference_asset_id": combination_font["id"] if (t, g) == (1, 0) else None,
            }
            for t in range(2) for g in range(2)
        ],
        "size": "1024x1024", "aspect_ratio": "1:1", "quality": "high",
        "output_format": "png", "concurrency": 2,
    })
    assert created.status_code in {200, 202}, created.text
    root_id = created.json()["workflow_job_id"]
    assert created.json()["analysis_call_target"] == 0
    assert created.json()["prompt_mode"] == "direct"
    assert created.json()["submission_kind"] == "production"
    assert created.json()["workspace_batch_id"] is None
    assert created.json()["status"] == "awaiting_prompt_confirmation"
    assert len(created.json()["template_prompts"]) == 2

    async with identity_test_context["session_factory"]() as session:
        prompt_records = list((await session.scalars(select(BatchTryOnTemplatePrompt).where(
            BatchTryOnTemplatePrompt.workflow_job_id == root_id,
        ).order_by(BatchTryOnTemplatePrompt.template_id))).all())
        assert len(prompt_records) == 2
        assert all(record.analysis_job_id is None for record in prompt_records)
        assert all(record.prompt_status == "effective" for record in prompt_records)
        assert all(record.generated_final_prompt == record.analysis_prompt_used for record in prompt_records)
        root = await session.get(Job, root_id)
        assert root is not None
        assert root.status == "succeeded"
        assert root.celery_task_id is None
        assert root.input_json["metadata"]["workflow_role"] == "direct_prompt"
        assert root.result_json["metadata"]["prompt_mode"] == "direct_preset"
        reservation = await session.get(QuotaReservation, root.quota_reservation_id)
        assert reservation is not None
        assert reservation.status == "released"

    latest = await client.get(f"/api/v1/batch-tryon/workflows?project_id={project_id}", headers=headers)
    assert latest.status_code == 200, latest.text
    assert latest.json()["status"] == "awaiting_prompt_confirmation"
    assert latest.json()["garment_profile"] is None
    assert latest.json()["template_profiles"] == {}
    assert latest.json()["batch_id"] is None
    assert all(item["prompt_status"] == "effective" for item in latest.json()["template_prompts"])
    assert all(item["analysis_job_id"] is None for item in latest.json()["template_prompts"])
    assert all(item["generated_final_prompt"] == item["analysis_prompt_used"] for item in latest.json()["template_prompts"])

    submitted = await client.post(
        f"/api/v1/batch-tryon/workflows/{root_id}/submit",
        headers=headers,
        json={"idempotency_key": "workflow-image-submit-001"},
    )
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["batch_id"]
    assert submitted.json()["status"] == "generating"
    batch_id = submitted.json()["batch_id"]
    batch = await client.get(f"/api/v1/job-batches/{batch_id}", headers=headers)
    assert batch.status_code == 200, batch.text
    assert batch.json()["total_jobs"] == 4
    assert {job["client_item_id"] for job in batch.json()["jobs"]} == {
        "item-0-0", "item-0-1", "item-1-0", "item-1-1",
    }
    async with identity_test_context["session_factory"]() as session:
        image_jobs = list((await session.scalars(select(Job).where(Job.batch_id == batch_id))).all())
        jobs_by_item = {job.client_item_id: job for job in image_jobs}
        assert jobs_by_item["item-0-0"].input_json["reference_asset_ids"] == [
            templates[0]["id"], garments[0]["id"], default_font["id"],
        ]
        assert jobs_by_item["item-1-0"].input_json["reference_asset_ids"] == [
            templates[1]["id"], garments[0]["id"], combination_font["id"],
        ]
        assert len(jobs_by_item["item-0-1"].input_json["reference_asset_ids"]) == 2
        assert "REFERENCE IMAGE 3 — CUSTOM TYPOGRAPHY ONLY" in jobs_by_item["item-0-0"].input_json["prompt"]
        assert all(job.input_json["metadata"]["workflow"] == "batch_tryon_server_workflow" for job in image_jobs)
        assert all(job.input_json["metadata"]["template_prompt_id"] for job in image_jobs)
        assert all(job.input_json["metadata"]["prompt_version"] == 1 for job in image_jobs)
        assert all(job.input_json["metadata"]["effective_prompt_snapshot"] for job in image_jobs)
        assert {job.input_json["metadata"]["template_type"] for job in image_jobs} == {"pure_white", "gift_scene"}
        prompts_by_type = {
            job.input_json["metadata"]["template_type"]: job.input_json["prompt"] for job in image_jobs
        }
        assert "PURE WHITE PRODUCT LAYOUT" in prompts_by_type["pure_white"]
        assert "GIFT SCENE" in prompts_by_type["gift_scene"]
        assert all("analysis_prompt_used" not in job.input_json["metadata"] for job in image_jobs)


async def test_server_workflow_can_opt_in_to_ai_prompt_analysis(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    await seed_workflow_resources(identity_test_context)
    headers = await auth_headers(client)
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "AI prompt workflow", "draft": {},
    })).json()
    template = await upload(client, headers, "model_template", "front.png")
    garment = await upload(client, headers, "garment", "01-shirt.png")

    created = await client.post("/api/v1/batch-tryon/workflows", headers=headers, json={
        "project_id": project["id"],
        "name": "AI prompt workflow",
        "idempotency_key": "workflow-ai-prompt-001",
        "generation_mode": "normal_tryon",
        "prompt_mode": "ai_analysis",
        "templates": [{
            "template_id": "template-ai", "asset_id": template["id"],
            "name": template["filename"], "order": 0, "template_type": "pure_white",
        }],
        "garments": [{
            "garment_id": "garment-ai", "asset_id": garment["id"],
            "filename": garment["filename"], "order": 0,
        }],
        "combinations": [{
            "client_item_id": "item-ai", "template_id": "template-ai",
            "garment_id": "garment-ai", "order": 0,
        }],
        "size": "1024x1024", "aspect_ratio": "1:1", "quality": "high",
        "output_format": "png", "concurrency": 1,
    })

    assert created.status_code == 202, created.text
    body = created.json()
    assert body["prompt_mode"] == "ai_analysis"
    assert body["analysis_call_target"] == 1
    assert body["status"] == "analyzing_prompts"
    assert len(body["template_prompts"]) == 1
    assert body["template_prompts"][0]["prompt_status"] == "analyzing"
    assert body["template_prompts"][0]["analysis_job_id"]

    async with identity_test_context["session_factory"]() as session:
        analysis_job = await session.get(Job, body["template_prompts"][0]["analysis_job_id"])
        assert analysis_job is not None
        assert analysis_job.operation_code == "batch_tryon.prompt_analyze"
        assert analysis_job.input_json["reference_asset_ids"] == [template["id"], garment["id"]]
        assert analysis_job.input_json["metadata"]["prompt_mode"] == "ai_analysis"
        assert analysis_job.input_json["system_prompt"] == body["template_prompts"][0]["analysis_prompt_used"]
        assert analysis_job.input_json["user_prompt"] == ""
        assert "REFERENCE IMAGE ORDER" not in analysis_job.input_json["system_prompt"]


async def test_validation_prompt_analysis_auto_submits_the_sample_batch(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    await seed_workflow_resources(identity_test_context)
    headers = await auth_headers(client)
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "Validation workflow", "draft": {},
    })).json()
    template = await upload(client, headers, "model_template", "validation-template.png")
    garment = await upload(client, headers, "garment", "validation-garment.png")

    created = await client.post("/api/v1/batch-tryon/workflows", headers=headers, json={
        "project_id": project["id"], "name": "Validation workflow",
        "idempotency_key": "validation-workflow-001", "prompt_mode": "ai_analysis",
        "submission_kind": "validation",
        "templates": [{
            "template_id": "validation-template", "asset_id": template["id"],
            "name": template["filename"], "order": 0, "template_type": "pure_white",
        }],
        "garments": [{
            "garment_id": "validation-garment", "asset_id": garment["id"],
            "filename": garment["filename"], "order": 0,
        }],
        "combinations": [{
            "client_item_id": "validation:item-1", "template_id": "validation-template",
            "garment_id": "validation-garment", "order": 0,
        }],
        "size": "1024x1024", "aspect_ratio": "1:1", "quality": "high",
        "output_format": "png", "concurrency": 1,
    })
    assert created.status_code == 202, created.text
    assert created.json()["submission_kind"] == "validation"
    analysis_id = created.json()["template_prompts"][0]["analysis_job_id"]

    async with identity_test_context["session_factory"]() as session:
        analysis = await session.get(Job, analysis_id)
        analysis.status = "succeeded"
        analysis.progress = 100
        analysis.finished_at = datetime.now(timezone.utc)
        analysis.result_json = {"metadata": {
            "text": "Only replace the garment and preserve the complete template composition.",
        }}
        await session.flush()
        batch = await continue_batch_tryon_workflow(
            session, Settings(_env_file=None), planning_job=analysis,
        )
        assert batch is not None
        assert batch.batch_kind == "validation"
        assert batch.total_jobs == 1
        jobs = list((await session.scalars(select(Job).where(Job.batch_id == batch.id))).all())
        assert len(jobs) == 1
        assert jobs[0].client_item_id == "validation:item-1"


async def test_standard_prompt_analysis_uses_each_templates_first_actual_combination(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    await seed_workflow_resources(identity_test_context)
    headers = await auth_headers(client)
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "One-to-one prompt workflow", "draft": {},
    })).json()
    template_a = await upload(client, headers, "model_template", "template-01.png")
    template_b = await upload(client, headers, "model_template", "template-02.png")
    garment_a = await upload(client, headers, "garment", "garment-0000531.png")
    garment_b = await upload(client, headers, "garment", "garment-0000532.png")
    font_b = await upload(client, headers, "style_reference", "font-0000532.png")

    response = await client.post("/api/v1/batch-tryon/workflows", headers=headers, json={
        "project_id": project["id"],
        "name": "One-to-one prompt workflow",
        "idempotency_key": "workflow-one-to-one-prompt-001",
        "generation_mode": "normal_tryon",
        "prompt_mode": "ai_analysis",
        "templates": [
            {"template_id": "template-a", "asset_id": template_a["id"], "name": template_a["filename"], "order": 0, "template_type": "pure_white"},
            {"template_id": "template-b", "asset_id": template_b["id"], "name": template_b["filename"], "order": 1, "template_type": "gift_scene"},
        ],
        "garments": [
            {"garment_id": "garment-a", "asset_id": garment_a["id"], "filename": garment_a["filename"], "order": 0},
            {"garment_id": "garment-b", "asset_id": garment_b["id"], "filename": garment_b["filename"], "order": 1, "font_reference_asset_id": font_b["id"]},
        ],
        "combinations": [
            {"client_item_id": "pair-a", "template_id": "template-a", "garment_id": "garment-a", "order": 0},
            {"client_item_id": "pair-b", "template_id": "template-b", "garment_id": "garment-b", "order": 1},
        ],
        "size": "1024x1024", "aspect_ratio": "1:1", "quality": "high",
        "output_format": "png", "concurrency": 2,
    })

    assert response.status_code == 202, response.text
    records = response.json()["template_prompts"]
    assert {record["garment_id"] for record in records} == {"garment-a", "garment-b"}
    async with identity_test_context["session_factory"]() as session:
        jobs = list((await session.scalars(select(Job).where(
            Job.id.in_([record["analysis_job_id"] for record in records])
        ))).all())
        references = {tuple(job.input_json["reference_asset_ids"]) for job in jobs}
        assert references == {
            (template_a["id"], garment_a["id"]),
            (template_b["id"], garment_b["id"], font_b["id"]),
        }


async def test_detailed_prompt_workflow_uses_luna_for_every_combination(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    await seed_workflow_resources(identity_test_context)
    headers = await auth_headers(client)
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "Detailed prompt workflow", "draft": {},
    })).json()
    template = await upload(client, headers, "model_template", "front.png")
    garment_a = await upload(client, headers, "garment", "01-shirt.png")
    garment_b = await upload(client, headers, "garment", "02-shirt.png")
    font_default = await upload(client, headers, "style_reference", "font-default.png")
    font_override = await upload(client, headers, "style_reference", "font-override.png")

    response = await client.post("/api/v1/batch-tryon/workflows", headers=headers, json={
        "project_id": project["id"],
        "name": "Detailed prompt workflow",
        "idempotency_key": "workflow-detailed-prompt-001",
        "generation_mode": "normal_tryon",
        "prompt_mode": "ai_detailed",
        "templates": [{
            "template_id": "template-detail", "asset_id": template["id"],
            "name": template["filename"], "order": 0, "template_type": "pure_white",
        }],
        "garments": [
            {
                "garment_id": "garment-a", "asset_id": garment_a["id"],
                "filename": garment_a["filename"], "order": 0,
                "font_reference_asset_id": font_default["id"],
            },
            {"garment_id": "garment-b", "asset_id": garment_b["id"], "filename": garment_b["filename"], "order": 1},
        ],
        "combinations": [
            {"client_item_id": "item-a", "template_id": "template-detail", "garment_id": "garment-a", "order": 0},
            {
                "client_item_id": "item-b", "template_id": "template-detail",
                "garment_id": "garment-b", "order": 1,
                "font_reference_asset_id": font_override["id"],
            },
        ],
        "size": "1024x1024", "aspect_ratio": "1:1", "quality": "high",
        "output_format": "png", "concurrency": 2,
    })

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["prompt_mode"] == "ai_detailed"
    assert body["analysis_call_target"] == 2
    assert len(body["template_prompts"]) == 2
    assert {record["client_item_id"] for record in body["template_prompts"]} == {"item-a", "item-b"}
    assert {record["garment_id"] for record in body["template_prompts"]} == {"garment-a", "garment-b"}

    async with identity_test_context["session_factory"]() as session:
        jobs = list((await session.scalars(select(Job).where(
            Job.id.in_([record["analysis_job_id"] for record in body["template_prompts"]])
        ))).all())
        assert len(jobs) == 2
        assert all(job.operation_code == "batch_tryon.prompt_analyze_detailed" for job in jobs)
        assert all(job.model_code == "gpt-5.6-luna" for job in jobs)
        references = {tuple(job.input_json["reference_asset_ids"]) for job in jobs}
        assert references == {
            (template["id"], garment_a["id"], font_default["id"]),
            (template["id"], garment_b["id"], font_override["id"]),
        }
        records = list((await session.scalars(select(BatchTryOnTemplatePrompt).where(
            BatchTryOnTemplatePrompt.workflow_job_id == body["workflow_job_id"],
        ))).all())
        prompt_by_job_id = {record.analysis_job_id: record.analysis_prompt_used for record in records}
        assert all(job.input_json["system_prompt"] == prompt_by_job_id[job.id] for job in jobs)
        assert all(job.input_json["user_prompt"] == "" for job in jobs)
        assert all("精细逐图分析要求" not in job.input_json["system_prompt"] for job in jobs)
        assert all("REFERENCE IMAGE ORDER" not in job.input_json["system_prompt"] for job in jobs)
        assert {record.font_reference_asset_id for record in records} == {font_default["id"], font_override["id"]}

        jobs_by_item = {job.input_json["metadata"]["client_item_id"]: job for job in jobs}
        first_analysis = jobs_by_item["item-a"]
        first_analysis.status = JobStatus.SUCCEEDED.value
        first_analysis.progress = 100
        first_analysis.finished_at = datetime.now(timezone.utc)
        first_analysis.result_json = {"metadata": {
            "text": "只替换当前服装，并严格保留模板构图、商品事实和全部未要求变化的内容。",
        }}
        await session.flush()

        batch = await continue_batch_tryon_workflow(
            session, Settings(_env_file=None), planning_job=first_analysis,
        )
        assert batch is not None
        image_jobs = list((await session.scalars(select(Job).where(
            Job.batch_id == batch.id,
        ).order_by(Job.client_item_id))).all())
        assert len(image_jobs) == 2
        image_by_item = {job.client_item_id: job for job in image_jobs}
        assert image_by_item["item-a"].status == JobStatus.DISPATCHING.value
        assert image_by_item["item-a"].input_json["metadata"]["awaiting_luna"] is False
        assert image_by_item["item-b"].status == JobStatus.WAITING_FOR_RESOURCE.value
        assert image_by_item["item-b"].input_json["metadata"]["awaiting_luna"] is True

        second_analysis = jobs_by_item["item-b"]
        second_analysis.status = JobStatus.SUCCEEDED.value
        second_analysis.progress = 100
        second_analysis.finished_at = datetime.now(timezone.utc)
        second_analysis.result_json = {"metadata": {
            "text": "准确替换为当前服装，保持模板人物、环境、构图及当前商品细节一致。",
        }}
        await session.flush()

        continued = await continue_batch_tryon_workflow(
            session, Settings(_env_file=None), planning_job=second_analysis,
        )
        assert continued is not None
        await session.refresh(image_by_item["item-b"])
        assert image_by_item["item-b"].status == JobStatus.DISPATCHING.value
        assert image_by_item["item-b"].input_json["metadata"]["awaiting_luna"] is False


async def test_workflow_uses_the_same_clean_front_reference_for_analysis_and_generation(
    identity_test_context, monkeypatch,
) -> None:
    client = identity_test_context["client"]
    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", lambda *args, **kwargs: None)
    await seed_workflow_resources(identity_test_context)
    headers = await auth_headers(client)
    project = (await client.post("/api/v1/projects", headers=headers, json={
        "project_type": "batch_tryon", "name": "Clean reference workflow", "draft": {},
    })).json()
    template = await upload(client, headers, "model_template", "front-model.png")
    garment = await upload(client, headers, "garment", "front-back-source.png")
    clean_front_response = await client.post(
        "/api/v1/assets/garment-references", headers=headers,
        data={
            "source_asset_id": garment["id"], "garment_view": "front", "transform_type": "crop",
            "transform_metadata": json.dumps({
                "crop": {"x": 0, "y": 0, "width": 0.5, "height": 1}, "provider_edit_mask": False,
            }),
        },
        files={"file": ("clean-front.png", PNG, "image/png")},
    )
    assert clean_front_response.status_code == 201, clean_front_response.text
    clean_front = clean_front_response.json()
    response = await client.post("/api/v1/batch-tryon/workflows", headers=headers, json={
        "project_id": project["id"], "name": "Clean reference workflow",
        "idempotency_key": "workflow-clean-front-001", "prompt_mode": "ai_analysis",
        "templates": [{
            "template_id": "front-template", "asset_id": template["id"], "name": "front-model",
            "order": 0, "template_type": "pure_white", "garment_view": "front",
        }],
        "garments": [{
            "garment_id": "source-garment", "asset_id": garment["id"], "filename": "front-back-source.png",
            "order": 0, "front_reference_asset_id": clean_front["id"],
        }],
        "combinations": [{
            "client_item_id": "clean-front-item", "template_id": "front-template",
            "garment_id": "source-garment", "order": 0,
        }],
        "size": "1024x1024", "aspect_ratio": "1:1", "quality": "high",
        "output_format": "png", "concurrency": 1,
    })
    assert response.status_code == 202, response.text
    analysis_id = response.json()["template_prompts"][0]["analysis_job_id"]
    async with identity_test_context["session_factory"]() as session:
        analysis = await session.get(Job, analysis_id)
        assert analysis.input_json["reference_asset_ids"] == [template["id"], clean_front["id"]]
        assert analysis.input_json["metadata"]["garment_asset_id"] == garment["id"]
        assert analysis.input_json["metadata"]["effective_garment_reference_asset_ids"] == [clean_front["id"]]
        assert analysis.input_json["metadata"]["effective_garment_reference_filename"] == "clean-front.png"
        assert analysis.input_json["metadata"]["effective_garment_reference_filenames"] == ["clean-front.png"]
        record = await session.scalar(select(BatchTryOnTemplatePrompt).where(
            BatchTryOnTemplatePrompt.analysis_job_id == analysis_id,
        ))
        record.generated_final_prompt = "Replace only the garment using the current clean garment reference."
        record.prompt_status = "effective"
        analysis.status = "succeeded"
        await session.flush()
        batch, jobs, created = await submit_confirmed_batch_tryon_workflow(
            session, Settings(_env_file=None), organization_id=analysis.organization_id,
            user_id=analysis.created_by, workflow_job_id=response.json()["workflow_job_id"],
            idempotency_key="clean-front-generate-001",
        )
        assert created is True and len(jobs) == 1
        assert jobs[0].input_json["reference_asset_ids"] == [template["id"], clean_front["id"]]
        assert jobs[0].input_json["metadata"]["garment_asset_id"] == garment["id"]
        assert jobs[0].input_json["metadata"]["effective_garment_reference_asset_ids"] == [clean_front["id"]]

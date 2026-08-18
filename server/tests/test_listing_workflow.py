from base64 import b64decode
from datetime import datetime, timezone

from httpx import AsyncClient

from sqlalchemy import select

from app.core.errors import AppError
from app.models.identity import OrganizationMember, User
from app.models.listing_workflow import (
    CategoryImageTemplate, CategorySkill, ListingGenerationSession, ListingVersion, ProductAnalysisResult, ProductCategory,
)
from app.models.tasks import Job
from app.services.category_listing_service import (
    build_analysis_segment,
    build_image_prompts,
    build_listing_version_image_prompts,
    build_listing_content_optimization_prompts,
    normalize_bilingual_listing_content,
    normalize_analysis_payload,
    parse_json_object,
)
from app.services.prompt_optimizer_service import (
    IMAGE_PROMPT_OPTIMIZER_SYSTEM_PROMPT,
    build_image_prompt_optimizer_input,
    clean_optimized_prompt,
)
from app.services.listing_image_task_group_service import aggregate_group_status
from app.services.listing_image_module_service import (
    STANDARD_MODULE_CODES,
    build_listing_image_modules,
    normalize_listing_product_profile,
)
from app.services.smart_image_variation_service import (
    FREE_BASE_PROMPT, build_free_variation_base_prompt, build_variation_prompt,
    validate_variation_skill_config, variation_config,
)


PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def _listing_module_fixture() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    analysis: dict[str, object] = {
        "product_name": "Custom American Football Jersey",
        "main_color": "cardinal red",
        "secondary_color": "white",
        "neck_type": "V-neck",
        "fabric_style": "mesh texture",
        "graphic_elements": ["front wordmark", "back number"],
        "number_presence": True,
        "customizable": True,
        "custom_fields": ["Player Name", "Back Number"],
        "target_audience": "adult football fans",
        "usage_scenarios": ["game day", "casual wear"],
    }
    listing: dict[str, object] = {
        "title": {"en": "Custom American Football Jersey", "zh": "定制橄榄球衣"},
        "bullet_points": [
            {"en": "Visible V-neck and mesh texture", "zh": "清晰V领与网眼纹理"},
        ],
    }
    skill: dict[str, object] = {
        "category_name": "橄榄球衣", "category_code": "american_football_jersey",
        "skill_name": "橄榄球衣默认Skill", "skill_version": 3,
    }
    return analysis, listing, skill


def test_listing_image_modules_build_six_distinct_skill_driven_modules() -> None:
    analysis, listing, skill = _listing_module_fixture()
    modules, prompts = build_listing_image_modules(
        analysis_snapshot=analysis, listing_snapshot=listing, skill_snapshot=skill,
    )

    assert tuple(module["code"] for module in modules) == STANDARD_MODULE_CODES
    assert set(prompts) == set(STANDARD_MODULE_CODES)
    assert "pure #FFFFFF background" in prompts["pure_white"]
    assert "four-step product customization infographic" in prompts["custom_process"]
    assert "American football stadium" in prompts["stadium_scene"]
    assert "personalized sports-gift scene" in prompts["gift_scene"]
    assert "3–5 truthful close-ups" in prompts["detail_display"]
    assert "non-stadium settings" in prompts["casual_scene"]
    assert len(set(prompts.values())) == 6


def test_listing_image_profile_normalizes_legacy_fields_without_mutating_source() -> None:
    analysis, listing, skill = _listing_module_fixture()
    source = dict(analysis)
    profile = normalize_listing_product_profile(analysis, listing, skill)

    assert profile["collar_type"] == "V-neck"
    assert profile["fabric_texture"] == "mesh texture"
    assert profile["sport_type"] == "American Football"
    assert profile["custom_fields"] == ["Player Name", "Back Number"]
    assert analysis == source


def test_listing_image_module_override_is_scoped_and_rebuilds_prompt() -> None:
    analysis, listing, skill = _listing_module_fixture()
    original_analysis = dict(analysis)
    modules, prompts = build_listing_image_modules(
        analysis_snapshot=analysis, listing_snapshot=listing, skill_snapshot=skill,
        selected_codes=["stadium_scene"],
        attribute_overrides={"stadium_scene": {"target_customer": "women football supporters"}},
    )

    stadium = next(module for module in modules if module["code"] == "stadium_scene")
    target = next(item for item in stadium["used_attributes"] if item["code"] == "target_customer")
    assert target["source"] == "module_override"
    assert "women football supporters" in prompts["stadium_scene"]
    assert analysis == original_analysis


def test_listing_image_custom_process_requires_verified_customization() -> None:
    analysis, listing, skill = _listing_module_fixture()
    analysis.update({"customizable": False, "custom_fields": [], "number_presence": False})

    modules, prompts = build_listing_image_modules(
        analysis_snapshot=analysis, listing_snapshot=listing, skill_snapshot=skill,
        selected_codes=["pure_white"],
    )

    custom = next(module for module in modules if module["code"] == "custom_process")
    assert custom["available"] is False
    assert "custom_process" not in prompts


def test_listing_image_prompt_does_not_invent_unsupported_product_claims() -> None:
    analysis, listing, skill = _listing_module_fixture()
    _, prompts = build_listing_image_modules(
        analysis_snapshot=analysis, listing_snapshot=listing, skill_snapshot=skill,
        selected_codes=["detail_display"],
    )

    prompt = prompts["detail_display"]
    assert "Never add unsupported" in prompt
    assert "moisture-wicking" in prompt
    assert "official-team" in prompt
    assert "LOW-WEIGHT CREATIVE CONTEXT" in prompt


async def auth_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_category_prompt_builder_preserves_four_layers_and_image_type() -> None:
    skill = CategorySkill(
        category_id="category", skill_name="Football", skill_code="football", is_active=True, version=1,
        analysis_prompt="analysis", listing_title_prompt="title", bullet_points_prompt="bullets",
        a_plus_prompt="aplus", image_prompt_template="CATEGORY RULE: keep jersey numbers and athletic styling.",
        image_types_config=[{"code": "main", "name": "主图"}, {"code": "scene", "name": "场景图"}],
        prompt_rules={},
    )
    template = CategoryImageTemplate(
        category_id="category", template_name="Seven", template_code="seven", version=1, is_active=True,
        system_prompt="SYSTEM RULE: preserve all visible garment details.",
        image_type_prompts={"main": "MAIN TYPE RULE", "scene": "SCENE TYPE RULE"},
        default_image_types=["main", "scene"],
    )
    attributes = {"main_color": "red", "number_presence": True, "style_tags": ["game day"]}

    image_types, prompts, segment = build_image_prompts(
        template=template, skill=skill, attributes=attributes,
        selected_image_types=["scene"], user_prompt="Use dramatic stadium lighting.",
    )

    assert image_types == ["scene"]
    assert "SYSTEM RULE" in prompts["scene"]
    assert "CATEGORY RULE" in prompts["scene"]
    assert "main color: red" in prompts["scene"]
    assert "SCENE TYPE RULE" in prompts["scene"]
    assert "Use dramatic stadium lighting" in prompts["scene"]
    assert segment.index("main color") < prompts["scene"].index("USER CREATIVE DIRECTION")


def test_analysis_json_normalization_accepts_fenced_payload() -> None:
    payload = parse_json_object("""```json
    {"analysis":{"gender":"women","main_color":"red","style_tags":["sport"]},
     "listing_content":{"title":"Red Football Jersey","bullets":["One","Two"]},
     "suggested_user_prompt":"Game-day atmosphere"}
    ```""")
    schema = [
        {"code": "gender", "type": "text", "default": ""},
        {"code": "neck_type", "type": "text", "default": ""},
        {"code": "main_color", "type": "color", "default": ""},
        {"code": "style_tags", "type": "tags", "default": []},
    ]
    attributes, content, prompt = normalize_analysis_payload(payload, schema)

    assert attributes["gender"] == "women"
    assert attributes["neck_type"] == ""
    assert content["title"] == {"en": "Red Football Jersey", "zh": ""}
    assert content["bullet_points"][0] == {"id": "bullet-1", "en": "One", "zh": ""}
    assert prompt == "Game-day atmosphere"
    assert "main color: red" in build_analysis_segment(attributes)


def test_bilingual_listing_normalization_preserves_pairing_and_legacy_data() -> None:
    value = normalize_bilingual_listing_content({
        "title": {"en": "Custom Jersey", "zh": "定制球衣"},
        "bullet_points": [{"id": "bullet-a", "en": "Visible V-neck", "zh": "清晰V领"}],
        "search_terms": {"en": ["custom jersey"], "zh": ["定制球衣"]},
    })
    assert value["title"]["zh"] == "定制球衣"
    assert value["bullet_points"][0]["id"] == "bullet-a"
    legacy = normalize_bilingual_listing_content({"title": "Legacy", "bullet_points": ["One"]})
    assert legacy["title"] == {"en": "Legacy", "zh": ""}
    assert legacy["bullet_points"][0]["en"] == "One"


def test_listing_and_image_prompt_optimizers_are_rewriters_not_translators() -> None:
    skill = CategorySkill(
        category_id="category", skill_name="Football", skill_code="football", is_active=True, version=1,
        analysis_prompt="Analyze accurately", listing_title_prompt="No unsupported title claims",
        bullet_points_prompt="Keep bullets truthful", a_plus_prompt="A+", image_prompt_template="Preserve jersey",
        image_types_config=[{"code": "scene"}], prompt_rules={},
    )
    system, user = build_listing_content_optimization_prompts(
        direction="zh_to_en", listing_content=normalize_bilingual_listing_content({"title": {"en": "Old", "zh": "新标题"}}),
        category_name="橄榄球衣", analysis={"main_color": "blue"}, skill=skill,
    )
    assert "Do not translate literally" in user
    assert "Never invent product evidence" in system
    image_system, image_user = build_image_prompt_optimizer_input(
        category_name="橄榄球衣", image_type="scene", product_analysis={"main_color": "blue"},
        category_skill_rules={"preserve_numbers": True}, original_english_prompt="Use a white studio background and preserve the jersey details.",
        chinese_editing_instruction="改成夜晚球场，人物和衣服不变。",
    )
    assert image_system == IMAGE_PROMPT_OPTIMIZER_SYSTEM_PROMPT
    assert "not to translate" in image_system
    assert "Latest Chinese editing instructions" in image_user
    assert clean_optimized_prompt("```text\nCreate a realistic stadium scene while preserving every visible jersey detail.\n```").startswith("Create")


def test_listing_image_task_group_status_is_aggregated_from_child_jobs() -> None:
    running = [Job(status="succeeded"), Job(status="running"), Job(status="queued")]
    status, statistics, progress = aggregate_group_status(running)
    assert status == "running"
    assert statistics.succeeded == 1 and statistics.running == 1 and statistics.queued == 1
    assert progress == 33

    partial = [Job(status="succeeded"), Job(status="failed"), Job(status="cancelled")]
    status, statistics, progress = aggregate_group_status(partial)
    assert status == "partially_succeeded"
    assert statistics.failed == 1 and statistics.cancelled == 1
    assert progress == 100

    cancelling = [Job(status="running", cancel_requested_at=datetime.now(timezone.utc))]
    assert aggregate_group_status(cancelling)[0] == "cancel_requested"


def test_confirmed_listing_prompt_builder_reuses_immutable_skill_snapshot() -> None:
    version = ListingVersion(
        organization_id="organization",
        session_id="session",
        version_number=1,
        listing_snapshot={},
        analysis_snapshot={"main_color": "navy", "number": "12"},
        category_skill_snapshot={
            "system_prompt": "Keep the uploaded product identity unchanged.",
            "image_prompt_template": "Preserve every jersey graphic and number.",
            "image_type_prompts": {"main": "Create an Amazon main image on pure white."},
            "default_image_types": ["main"],
        },
        confirmed_at=datetime.now(timezone.utc),
        confirmed_by="user",
        created_by="user",
    )

    prompts = build_listing_version_image_prompts(version)

    assert list(prompts) == ["main"]
    assert "Keep the uploaded product identity unchanged" in prompts["main"]
    assert "main color: navy" in prompts["main"]
    assert "Amazon main image" in prompts["main"]


def test_skill_driven_variation_types_build_distinct_prompts_and_reject_empty_config() -> None:
    config = {
        "variation_config": {
            "enabled": True,
            "types": [
                {
                    "code": "scene", "name": "场景裂变", "prompt_rule": "Change the setting and lighting.",
                    "preserve_elements": ["颜色", "号码"], "allowed_changes": ["背景", "光线"],
                    "plans": [{"code": "stadium", "name": "球场", "prompt_template": "Use a game-day stadium."}],
                },
                {
                    "code": "model", "name": "模特裂变", "prompt_rule": "Change the model casting and pose.",
                    "preserve_elements": ["颜色", "号码"], "allowed_changes": ["模特", "动作"],
                    "plans": [{"code": "female", "name": "女性模特", "prompt_template": "Use a female sportswear model."}],
                },
            ],
        },
    }
    assert validate_variation_skill_config(config) == []
    version = ListingVersion(
        organization_id="organization", session_id="session", version_number=1,
        listing_snapshot={"title": {"en": "Navy Number 12 Jersey", "zh": ""}, "bullet_points": []},
        analysis_snapshot={"main_color": "navy", "number": "12"},
        category_skill_snapshot={
            "system_prompt": "Preserve the exact product.", "image_prompt_template": "Keep all jersey graphics.",
            "image_prompt_config": {"system_prompt": "Preserve the exact product.", "category_prompt": "Keep all jersey graphics.", **config},
        },
        confirmed_at=datetime.now(timezone.utc), confirmed_by="user", created_by="user",
    )
    scene = build_variation_prompt(
        version, variation_type=config["variation_config"]["types"][0],
        plan=config["variation_config"]["types"][0]["plans"][0], custom_plan=False,
    )
    model = build_variation_prompt(
        version, variation_type=config["variation_config"]["types"][1],
        plan=config["variation_config"]["types"][1]["plans"][0], custom_plan=False,
    )
    assert "Change the setting and lighting" in scene and "game-day stadium" in scene
    assert "Change the model casting and pose" in model and "female sportswear model" in model
    assert scene != model
    assert "Navy Number 12 Jersey" in scene
    try:
        variation_config({"image_prompt_config": {}})
        raise AssertionError("missing variation config should fail")
    except AppError as error:
        assert error.message == "当前品类暂未配置图片裂变方案，请联系管理员在Skill配置台中完成配置。"


def test_free_variation_prompt_is_neutral_without_skill_and_skill_is_lower_priority() -> None:
    neutral = build_free_variation_base_prompt({"available": False})
    assert FREE_BASE_PROMPT in neutral
    assert "Chinese instructions are the primary creative direction" in neutral
    assert "OPTIONAL CATEGORY/SKILL GUIDANCE" not in neutral

    assisted = build_free_variation_base_prompt({
        "available": True,
        "prompt_context": {"system_prompt": "Preserve the exact jersey number.", "category_prompt": "Use sports styling."},
    })
    assert "OPTIONAL CATEGORY/SKILL GUIDANCE (lower priority" in assisted
    assert "Preserve the exact jersey number" in assisted


async def test_free_variation_project_works_without_category_skill(identity_test_context) -> None:
    client = identity_test_context["client"]
    member = await auth_headers(client, "first-admin@example.com", "correct-password")
    uploaded = await client.post(
        "/api/v1/assets", headers=member, data={"category": "temporary"},
        files={"file": ("free-source.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    asset_id = uploaded.json()["id"]

    created = await client.post("/api/v1/listing-workbench/free-variation-projects", headers=member, json={
        "asset_ids": [asset_id], "primary_asset_id": asset_id,
    })
    assert created.status_code == 201, created.text
    context = created.json()
    assert context["asset_ids"] == [asset_id]
    assert context["primary_asset_id"] == asset_id
    assert context["selected_category_id"] is None

    recommendation = await client.get("/api/v1/listing-workbench/free-variation-recommendations", headers=member)
    assert recommendation.status_code == 200, recommendation.text
    assert recommendation.json()["available"] is False
    assert recommendation.json()["directions"] == []
    assert recommendation.json()["templates"] == []

    built = await client.post(
        f"/api/v1/listing-image-projects/{context['project_id']}/free-variation-prompt",
        headers=member,
        json={
            "chinese_prompt": "保持角色和服装不变，更换背景为橄榄球场",
            "template_fragments": ["保持角色不变", "更换背景为橄榄球场"],
        },
    )
    assert built.status_code == 200, built.text
    assert built.json()["image_type"] == "variation.free"
    assert built.json()["prompt_status"] == "needs_optimization"
    assert built.json()["recommendation"]["available"] is False

    restored = await client.get(
        f"/api/v1/listing-workbench/free-variation-projects/{context['project_id']}", headers=member,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["chinese_prompt"] == "保持角色和服装不变，更换背景为橄榄球场"
    assert restored.json()["template_fragments"] == ["保持角色不变", "更换背景为橄榄球场"]


async def test_admin_can_create_category_skill_and_bind_default(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")
    member = await auth_headers(client, "first-admin@example.com", "correct-password")

    created = await client.post("/api/v1/categories", headers=platform, json={
        "category_code": "football_jersey", "category_name": "橄榄球衣",
        "description": "Football jersey workflow", "sort_order": 10,
    })
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]

    forbidden = await client.post("/api/v1/categories", headers=member, json={
        "category_code": "forbidden", "category_name": "无权限",
    })
    assert forbidden.status_code == 403

    skill = await client.post("/api/v1/category-skills", headers=platform, json={
        "category_id": category_id, "skill_name": "橄榄球衣 Skill", "skill_code": "football_listing",
        "analysis_prompt": "Analyze visible football jersey attributes and return structured JSON only.",
        "listing_title_prompt": "Create a truthful American football jersey Amazon title.",
        "bullet_points_prompt": "Create five truthful American football jersey bullet points.",
        "a_plus_prompt": "Create truthful American football jersey A+ marketing copy.",
        "image_prompt_template": "Preserve the exact jersey graphics, colors, text and numbers in every image.",
        "image_types_config": [{"code": "main", "name": "主图"}],
        "prompt_rules": {"preserve_numbers": True},
    })
    assert skill.status_code == 201, skill.text
    skill_id = skill.json()["id"]

    template = await client.post("/api/v1/category-image-templates", headers=platform, json={
        "category_id": category_id, "template_name": "主图模板", "template_code": "football_main",
        "system_prompt": "Preserve every visible garment detail and create a truthful Amazon image.",
        "image_type_prompts": {"main": "Pure white background product-only main image."},
        "default_image_types": ["main"],
    })
    assert template.status_code == 201, template.text

    updated = await client.put(f"/api/v1/categories/{category_id}", headers=platform, json={
        "default_skill_id": skill_id, "default_image_template_id": template.json()["id"],
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["default_skill_name"] == "橄榄球衣 Skill"
    assert updated.json()["default_image_types"] == ["main"]

    visible = await client.get("/api/v1/categories", headers=member)
    assert visible.status_code == 200
    assert visible.json()[0]["category_code"] == "football_jersey"

    uploaded = await client.post(
        "/api/v1/assets", headers=member, data={"category": "product_reference"},
        files={"file": ("jersey.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 201


async def test_listing_confirmation_versions_output_projects_and_org_isolation(identity_test_context) -> None:
    client = identity_test_context["client"]
    member = await auth_headers(client, "first-admin@example.com", "correct-password")
    other_org = await auth_headers(client, "second-admin@example.com", "second-password")
    async with identity_test_context["session_factory"]() as session:
        user = await session.scalar(select(User).where(User.email == "first-admin@example.com"))
        membership = await session.scalar(select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == identity_test_context["first_org"],
        ))
        category = ProductCategory(category_code="football_test", category_name="橄榄球衣", is_active=True, sort_order=1, created_by=user.id, updated_by=user.id)
        session.add(category); await session.flush()
        skill = CategorySkill(
            category_id=category.id, skill_name="Football", skill_code="football", is_active=True, version=1,
            analysis_prompt="Analyze visible product details accurately.", listing_title_prompt="Create title accurately.",
            bullet_points_prompt="Create five bullets accurately.", a_plus_prompt="Create A+ modules accurately.",
            image_prompt_template="Preserve the exact uploaded jersey design and all visible details.",
            image_types_config=[{"code": "main", "name": "主图"}], prompt_rules={}, created_by=user.id, updated_by=user.id,
        )
        session.add(skill); await session.flush()
        template = CategoryImageTemplate(
            category_id=category.id, template_name="Main", template_code="main", version=1, is_active=True,
            system_prompt="Preserve all exact visible garment details and avoid unsupported additions.",
            image_type_prompts={"main": "Create an Amazon main image on white."}, default_image_types=["main"],
            created_by=user.id, updated_by=user.id,
        )
        session.add(template); await session.flush()
        category.default_skill_id = skill.id; category.default_image_template_id = template.id
        analysis = ProductAnalysisResult(
            organization_id=membership.organization_id, category_id=category.id, skill_id=skill.id,
            source_asset_ids=[], structured_attributes={"main_color": "blue"},
            listing_content={"title": "Blue Football Jersey", "bullet_points": ["Accurate visible design"]},
            created_by=user.id, updated_by=user.id,
        )
        session.add(analysis); await session.flush()
        workflow = ListingGenerationSession(
            organization_id=membership.organization_id, category_id=category.id, skill_id=skill.id,
            analysis_result_id=analysis.id, status="generated", source_asset_ids=[],
            listing_content=analysis.listing_content, created_by=user.id, updated_by=user.id,
        )
        session.add(workflow); await session.commit(); workflow_id = workflow.id

    blocked = await client.post("/api/v1/listing-image-projects", headers=member, json={"session_id": workflow_id})
    assert blocked.status_code == 409
    confirmed = await client.post(f"/api/v1/listing-workbench/sessions/{workflow_id}/confirm", headers=member, json={})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["listing_version_number"] == 1

    listed = await client.get("/api/v1/listing-workbench/sessions?limit=25", headers=member)
    assert listed.status_code == 200, listed.text
    listed_session = next(item for item in listed.json() if item["id"] == workflow_id)
    assert listed_session["category_name"] == "橄榄球衣"
    assert listed_session["listing_version_number"] == 1
    assert listed_session["confirmed_at"] is not None
    assert listed_session["variation_enabled"] is False

    other_org_list = await client.get("/api/v1/listing-workbench/sessions", headers=other_org)
    assert other_org_list.status_code == 200
    assert all(item["id"] != workflow_id for item in other_org_list.json())

    listing_project = await client.post("/api/v1/listing-image-projects", headers=member, json={"session_id": workflow_id})
    a_plus_project = await client.post("/api/v1/a-plus-projects", headers=member, json={"session_id": workflow_id})
    assert listing_project.status_code == 201, listing_project.text
    assert a_plus_project.status_code == 201, a_plus_project.text
    assert listing_project.json()["id"] != a_plus_project.json()["id"]
    assert listing_project.json()["kind"] == "listing_image"
    assert a_plus_project.json()["kind"] == "a_plus"
    assert [item["code"] for item in listing_project.json()["modules"]] == list(STANDARD_MODULE_CODES)
    assert next(item for item in listing_project.json()["modules"] if item["code"] == "custom_process")["available"] is False

    built_modules = await client.post(
        f"/api/v1/listing-image-projects/{listing_project.json()['id']}/build-prompts",
        headers=member,
        json={
            "selected_items": ["pure_white", "stadium_scene"],
            "module_attribute_overrides": {"stadium_scene": {"target_customer": "adult game-day fans"}},
        },
    )
    assert built_modules.status_code == 200, built_modules.text
    assert set(built_modules.json()["prompts"]) == {"pure_white", "stadium_scene"}
    assert "adult game-day fans" in built_modules.json()["prompts"]["stadium_scene"]
    prompt_items = await client.get(
        f"/api/v1/prompt-optimizer/projects/listing_image/{listing_project.json()['id']}/items",
        headers=member,
    )
    assert prompt_items.status_code == 200, prompt_items.text
    assert {item["prompt_item_id"] for item in prompt_items.json()} == {"pure_white", "stadium_scene"}

    denied = await client.get(f"/api/v1/listing-image-projects/{listing_project.json()['id']}", headers=other_org)
    assert denied.status_code == 404

    edited = await client.patch(f"/api/v1/listing-workbench/sessions/{workflow_id}", headers=member, json={
        "listing_content": {"title": "Blue Football Jersey Updated", "bullet_points": ["Updated accurate detail"]},
    })
    assert edited.status_code == 200
    assert edited.json()["status"] == "editing"
    stale = await client.patch(f"/api/v1/listing-workbench/sessions/{workflow_id}", headers=member, json={
        "listing_content": {"title": "Stale overwrite", "bullet_points": ["Must not win"]},
        "expected_state_version": edited.json()["state_version"] - 1,
    })
    assert stale.status_code == 409
    confirmed_v2 = await client.post(f"/api/v1/listing-workbench/sessions/{workflow_id}/confirm", headers=member, json={})
    assert confirmed_v2.status_code == 200
    assert confirmed_v2.json()["listing_version_number"] == 2

    options = await client.get(f"/api/v1/listing-workbench/sessions/{workflow_id}/output-options", headers=member)
    assert options.status_code == 200
    assert options.json()["listing_snapshot"]["title"] == {"en": "Blue Football Jersey Updated", "zh": ""}
    assert options.json()["listing_snapshot"]["bullet_points"][0]["zh"] == ""
    assert options.json()["category_name"] == "橄榄球衣"
    assert options.json()["listing_version_number"] == 2
    assert options.json()["listing_image_project"]["outdated"] is True
    assert options.json()["a_plus_project"]["outdated"] is True
    adopted = await client.patch(f"/api/v1/listing-image-projects/{listing_project.json()['id']}", headers=member, json={"adopt_latest_listing": True})
    assert adopted.status_code == 200
    assert adopted.json()["listing_version_number"] == 2
    still_old = await client.get(f"/api/v1/a-plus-projects/{a_plus_project.json()['id']}", headers=member)
    assert still_old.status_code == 200
    assert still_old.json()["listing_version_number"] == 1
    deleted = await client.delete(f"/api/v1/listing-image-projects/{listing_project.json()['id']}", headers=member)
    assert deleted.status_code == 204
    a_plus_survives = await client.get(f"/api/v1/a-plus-projects/{a_plus_project.json()['id']}", headers=member)
    assert a_plus_survives.status_code == 200
    session_survives = await client.get(f"/api/v1/listing-workbench/sessions/{workflow_id}", headers=member)
    assert session_survives.status_code == 200


async def test_category_skill_admin_version_publish_and_default(identity_test_context) -> None:
    client = identity_test_context["client"]
    platform = await auth_headers(client, "platform-admin@example.com", "platform-password")
    member = await auth_headers(client, "first-admin@example.com", "correct-password")
    category = await client.post("/api/v1/categories", headers=platform, json={
        "category_code": "skill_console_test", "category_name": "Skill Console Test",
    })
    assert category.status_code == 201, category.text
    created = await client.post("/api/v1/admin/category-skills", headers=platform, json={
        "category_id": category.json()["id"], "skill_name": "Configurable Skill",
        "skill_code": "configurable_skill", "marketplace": "amazon_us", "language": "en-US_zh-CN",
    })
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]
    missing_default = await client.get(
        f"/api/v1/listing-workbench/quick-options?category_id={category.json()['id']}", headers=member,
    )
    assert missing_default.status_code == 422
    assert missing_default.json()["error"]["message"] == "当前品类尚未配置默认Skill。"
    forbidden = await client.get(f"/api/v1/admin/category-skills/{skill_id}/versions", headers=member)
    assert forbidden.status_code == 403
    versions = await client.get(f"/api/v1/admin/category-skills/{skill_id}/versions", headers=platform)
    assert versions.status_code == 200, versions.text
    version = versions.json()[0]
    assert version["status"] == "draft"
    validated = await client.post(
        f"/api/v1/admin/category-skills/{skill_id}/versions/{version['id']}/validate", headers=platform,
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["valid"] is True
    published = await client.post(
        f"/api/v1/admin/category-skills/{skill_id}/versions/{version['id']}/publish", headers=platform,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    immutable = await client.put(
        f"/api/v1/admin/category-skills/{skill_id}/versions/{version['id']}", headers=platform,
        json={
            "analysis_config": version["analysis_config"], "listing_config": version["listing_config"],
            "translation_config": version["translation_config"], "image_prompt_config": version["image_prompt_config"],
            "a_plus_config": version["a_plus_config"], "change_summary": "illegal edit",
        },
    )
    assert immutable.status_code == 409
    defaulted = await client.post(
        f"/api/v1/admin/category-skills/{skill_id}/versions/{version['id']}/set-default", headers=platform,
    )
    assert defaulted.status_code == 200, defaulted.text
    assert defaulted.json()["default_published_version_id"] == version["id"]
    template = await client.post("/api/v1/category-image-templates", headers=platform, json={
        "category_id": category.json()["id"], "template_name": "快速主图模板", "template_code": "quick_main",
        "system_prompt": "Preserve the uploaded product exactly.",
        "image_type_prompts": {"main": "Create a white-background Amazon main image."},
        "default_image_types": ["main"],
    })
    assert template.status_code == 201, template.text
    category_default = await client.put(f"/api/v1/categories/{category.json()['id']}", headers=platform, json={
        "default_skill_id": skill_id,
        "default_image_template_id": template.json()["id"],
    })
    assert category_default.status_code == 200, category_default.text
    quick_options = await client.get(
        f"/api/v1/listing-workbench/quick-options?category_id={category.json()['id']}", headers=member,
    )
    assert quick_options.status_code == 200, quick_options.text
    assert quick_options.json()["skill_version_id"] == version["id"]
    assert quick_options.json()["skill_version_number"] == 1
    assert quick_options.json()["default_image_types"]
    v2 = await client.post(f"/api/v1/admin/category-skills/{skill_id}/versions", headers=platform, json={})
    assert v2.status_code == 201, v2.text
    assert v2.json()["version_number"] == 2
    assert v2.json()["status"] == "draft"

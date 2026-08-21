from app.schemas.attachment_output_edit import AttachmentOutputEditItemRequest
from app.schemas.attachment_planning import AttachmentReferenceLibraryCreateRequest
from app.services.attachment_output_edit_service import _detect_explicit_overrides, compile_output_edit_prompt
from app.services.attachment_planning_service import attachment_module_definitions


def test_output_edit_detects_explicit_identity_overrides() -> None:
    assert _detect_explicit_overrides("把衣服换成另一件，并更换模特") == ["product_identity", "model_identity"]
    assert _detect_explicit_overrides("只把背景改成夜晚球场") == []


def test_output_edit_prompt_preserves_locks_without_replanning() -> None:
    prompt = compile_output_edit_prompt(
        instruction="把背景改为夜晚球场", edit_scope="background",
        product_lock={"colors": ["红色"], "logos": ["胸前标志"]},
        model_snapshot=[{"name": "运动男模 A"}], overrides=[],
    )
    assert "当前生成结果" in prompt
    assert "把背景改为夜晚球场" in prompt
    assert "红色" in prompt
    assert "运动男模 A" in prompt
    assert "重新策划" in prompt


def test_output_edit_prompt_includes_frozen_library_context() -> None:
    prompt = compile_output_edit_prompt(
        instruction="把背景改成参考图氛围", edit_scope="background",
        product_lock={}, model_snapshot=[], overrides=[],
        library_context=[{
            "library_item_id": "library-1", "reference_role": "SCENE",
            "guidance": "只参考酒吧构图，不继承商品", "state_version": 3,
            "understanding": {"version_number": 2, "status": "ready"},
        }],
    )
    assert "library-1" in prompt
    assert "只参考酒吧构图，不继承商品" in prompt
    assert "Role硬规则优先于Guidance" in prompt


def test_output_edit_item_accepts_no_review_or_final_fields() -> None:
    item = AttachmentOutputEditItemRequest(
        source_output_id="a" * 36, instruction="提高背景对比度",
    )
    assert item.edit_scope == "whole_image"
    assert item.override_confirmed is False


def test_reference_library_accepts_multiple_modules() -> None:
    payload = AttachmentReferenceLibraryCreateRequest(
        name="比赛日构图", module_keys=["stadium_scene", "casual_scene"],
        reference_role="SCENE", asset_id="a" * 36,
    )
    assert payload.module_keys == ["stadium_scene", "casual_scene"]


def test_reference_library_options_use_formal_attachment_modules() -> None:
    modules = attachment_module_definitions({
        "image_prompt_config": {
            "image_types": [{"code": "main_image", "name": "不应读取"}],
            "listing_image_modules": [{"code": "gift_scene", "name": "礼赠场景"}],
        },
    })
    assert [item["code"] for item in modules] == [
        "pure_white", "custom_process", "stadium_scene", "gift_scene", "detail_display", "casual_scene",
    ]
    assert next(item for item in modules if item["code"] == "gift_scene")["name"] == "礼赠场景"

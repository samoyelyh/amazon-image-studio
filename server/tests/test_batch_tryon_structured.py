import json
from copy import deepcopy

import pytest

from app.prompts.batch_tryon_structured import SCENE_RULES, STRUCTURED_FORMAT, structured_analysis_prompt
from app.providers.base import ProviderError, ProviderResult
from app.services.batch_tryon_structured_service import input_manifest, normalize_structured_result
from app.services.batch_tryon_prompt_service import build_template_prompt_composed_prompt


def document(garment_id="garment-a"):
    return {"task_type": "batch_garment_replacement", "total_garments": 1,
        "template_analysis": {"subject": "前景男性", "pose": "站姿", "view_direction": "正面",
            "original_clothing": "棒球衫", "lighting": "柔和侧光", "occlusions": ["手部"], "protected_elements": ["身份", "广告标题"]},
        "jobs": [{"garment_id": garment_id, "garment_type": "运动球衣", "view_direction": "正面", "garment_structure": "黑色V领短袖",
            "colors": ["酒红色衣身", "黑色领口"], "graphics": ["队徽"], "texts_and_numbers": ["TEAM", "06"],
            "replacement_region": "前景人物上装", "structural_changes": ["移除门襟重建V领"], "preservation_rules": ["保留背景文字"],
            "removal_rules": ["清除旧球衣标识"], "risk_level": "LOW", "needs_manual_review": False, "uncertainties": [],
            "generation_prompt": "以图A为固定模板，仅将前景男性上衣替换为图B酒红色黑色V领球衣，保留文字TEAM与号码06、脸部及背景标题。"}]}


def normalize(doc):
    return normalize_structured_result(ProviderResult([], "request-1", {"text": json.dumps(doc, ensure_ascii=False)}),
        {"analysis_format": STRUCTURED_FORMAT, "garment_id": "garment-a"})


def test_only_current_chinese_generation_prompt_is_forwarded():
    doc = document()
    result = normalize(doc)
    assert result.metadata["text"] == doc["jobs"][0]["generation_prompt"]
    assert json.loads(result.metadata["raw_text"]) == doc
    assert result.metadata["structured_analysis"] == doc
    assert result.provider_request_id == "request-1"
    assert result.metadata["requires_manual_review"] is False


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(total_garments=4), lambda d: d.update(jobs=[]),
    lambda d: d["jobs"].append(deepcopy(d["jobs"][0])),
    lambda d: d["jobs"][0].update(garment_id="garment-b"),
    lambda d: d["jobs"][0].update(risk_level="UNKNOWN"),
    lambda d: d["jobs"][0].update(needs_manual_review="false"),
    lambda d: d["jobs"][0].update(generation_prompt=""),
    lambda d: d["jobs"][0].update(generation_prompt="Replace the current shirt only."),
    lambda d: d["jobs"][0].pop("uncertainties"),
    lambda d: d.update(unexpected="extra"),
])
def test_invalid_or_cross_garment_result_never_reaches_images(mutation):
    doc = document(); mutation(doc)
    with pytest.raises(ProviderError) as caught:
        normalize(doc)
    assert not caught.value.retryable


@pytest.mark.parametrize("text", ['```json\n{}\n```', '{"task_type":1,"task_type":2}', '中文分析而非JSON'])
def test_bad_json_does_not_fall_back_to_raw_prompt(text):
    with pytest.raises(ProviderError):
        normalize_structured_result(ProviderResult([], metadata={"text": text}),
            {"analysis_format": STRUCTURED_FORMAT, "garment_id": "garment-a"})


@pytest.mark.parametrize("updates", [{"risk_level": "HIGH"}, {"needs_manual_review": True}, {"uncertainties": ["姓名不可辨认"]}])
def test_risky_results_require_confirmation(updates):
    doc = document(); doc["jobs"][0].update(updates)
    assert normalize(doc).metadata["requires_manual_review"]


def test_legacy_text_mode_is_unchanged():
    result = ProviderResult([], metadata={"text": "Original English prompt"})
    assert normalize_structured_result(result, {}) is result


def test_manifest_is_stable_and_keeps_font_and_back_separate():
    value = json.loads(input_manifest(garment_id="stable-06", template_type="gift_scene",
        references=["template", "front", "font", "back"], garment_references=["front", "back"], font_reference="font"))["input_manifest"]
    assert value["garment_id"] == "stable-06"
    assert value["images"][2]["role"].startswith("图C")
    assert "背面" in value["images"][3]["role"]


@pytest.mark.parametrize("template_type", list(SCENE_RULES))
def test_scene_aware_prompt_is_complete(template_type):
    prompt = structured_analysis_prompt(template_type)
    assert SCENE_RULES[template_type] in prompt
    assert "图C" in prompt and "total_garments固定1" in prompt


def test_structured_composer_does_not_reappend_legacy_base():
    prompt = document()["jobs"][0]["generation_prompt"]
    composed = build_template_prompt_composed_prompt(template_type="casual_scene", reusable_final_prompt=prompt,
        garment_filename="06.png", template_name="model", structured_analysis=True)
    assert composed.effective_prompt == prompt
    assert "CURRENT-GARMENT OVERRIDE" not in composed.effective_prompt


@pytest.mark.asyncio
async def test_review_auto_regeneration_stops_before_image_job_when_manual_review_required():
    from app.models.tasks import Job
    from app.core.config import Settings
    from app.services.batch_tryon_review_service import continue_detailed_review_auto_regeneration
    job = Job(input_json={"metadata": {"workflow_role": "review_detailed_analysis", "auto_regenerate": True}},
        result_json={"metadata": {"text": "中文换衣提示词", "requires_manual_review": True}})
    image, created = await continue_detailed_review_auto_regeneration(None, Settings(_env_file=None), analysis_job=job)
    assert image is None and created is False
    assert job.result_json["metadata"]["auto_regeneration_status"] == "awaiting_manual_confirmation"

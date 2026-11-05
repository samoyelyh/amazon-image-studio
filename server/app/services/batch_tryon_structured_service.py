"""Strict per-garment structured result validation on the existing Job path."""
from dataclasses import replace
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.prompts.batch_tryon_structured import STRUCTURED_FORMAT
from app.providers.base import ProviderError, ProviderResult

Text = Annotated[str, Field(strict=True, min_length=1, max_length=6000)]
TextList = Annotated[list[Text], Field(max_length=60)]


class TemplateAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    subject: Text
    pose: Text
    view_direction: Text
    original_clothing: Text
    lighting: Text
    occlusions: TextList
    protected_elements: TextList


class GarmentAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    garment_id: Annotated[str, Field(min_length=1, max_length=120)]
    garment_type: Text
    view_direction: Text
    garment_structure: Text
    colors: TextList
    graphics: TextList
    texts_and_numbers: TextList
    replacement_region: Text
    structural_changes: TextList
    preservation_rules: TextList
    removal_rules: TextList
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    needs_manual_review: bool
    uncertainties: TextList
    generation_prompt: Annotated[str, Field(min_length=1, max_length=30000)]


class StructuredAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_type: Literal["batch_garment_replacement"]
    total_garments: Literal[1]
    template_analysis: TemplateAnalysis
    jobs: Annotated[list[GarmentAnalysis], Field(min_length=1, max_length=1)]


def input_manifest(*, garment_id: str, template_type: str, references: list[str],
                   garment_references: list[str], font_reference: str | None,
                   extra_requirements: str = "") -> str:
    roles = []
    for index, asset_id in enumerate(references):
        role = "图A：固定模板" if index == 0 else (
            "图C：定制字体参考，不是服装" if asset_id == font_reference else
            "图B：当前服装有效参考" if asset_id == garment_references[0] else "当前服装的独立背面参考"
        )
        roles.append({"image_index": index + 1, "role": role})
    return json.dumps({"input_manifest": {"garment_id": garment_id, "total_garments": 1,
        "template_type": template_type, "images": roles, "extra_requirements": extra_requirements}}, ensure_ascii=False)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def normalize_structured_result(result: ProviderResult, metadata: dict[str, object]) -> ProviderResult:
    if metadata.get("analysis_format") != STRUCTURED_FORMAT:
        return result
    raw = str((result.metadata or {}).get("text") or "").strip()
    try:
        if len(raw.encode("utf-8")) > 150_000:
            raise ValueError("too large")
        document = StructuredAnalysis.model_validate(json.loads(raw, object_pairs_hook=_unique_object))
    except (ValueError, TypeError, ValidationError) as error:
        raise ProviderError("batch_tryon.structured_analysis_invalid",
            "Luna结构化结果不符合V1.1格式，未提交生图。请检查JSON字段、数量及格式后重新分析。") from error
    garment = document.jobs[0]
    if garment.garment_id != metadata.get("garment_id"):
        raise ProviderError("batch_tryon.analysis_garment_mismatch", "Luna返回的服装ID与当前任务不一致，已阻止串图。")
    narrative = [document.template_analysis.subject, document.template_analysis.pose,
        document.template_analysis.view_direction, document.template_analysis.original_clothing,
        document.template_analysis.lighting, garment.garment_type, garment.view_direction,
        garment.garment_structure, garment.replacement_region, garment.generation_prompt,
        *garment.structural_changes, *garment.preservation_rules, *garment.removal_rules, *garment.uncertainties]
    if any(not re.search(r"[\u3400-\u9fff]", text) for text in narrative):
        raise ProviderError("batch_tryon.analysis_language_invalid", "Luna分析说明和最终换衣提示词需要使用中文，未提交生图。")
    manual = garment.needs_manual_review or garment.risk_level == "HIGH" or bool(garment.uncertainties)
    garment.needs_manual_review = manual
    return replace(result, metadata={**(result.metadata or {}), "raw_text": raw,
        "text": garment.generation_prompt.strip(), "analysis_format": STRUCTURED_FORMAT,
        "structured_analysis": document.model_dump(), "requires_manual_review": manual})


def structured_result_metadata(job) -> dict[str, object]:
    return dict((job.result_json or {}).get("metadata") or {}) if job else {}

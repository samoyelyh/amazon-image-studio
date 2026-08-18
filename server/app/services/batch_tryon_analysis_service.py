from __future__ import annotations

import json
import re
from typing import Any


GARMENT_ANALYSIS_SYSTEM_PROMPT = """You analyze only reusable garment structure for virtual try-on.
Return one JSON object. Never copy colors, text, numbers, names, logos, teams, or graphics into reusable rules.
The first garment is a structural sample only; every later garment remains its own visual truth."""

TEMPLATE_ANALYSIS_SYSTEM_PROMPT = """You analyze a model or detail template for virtual try-on.
Return exactly one valid JSON object matching the requested schema. Do not return markdown, explanations,
questions, suggestions, or product copy. Describe only visible template composition and never invent product details."""

GARMENT_ANALYSIS_USER_PROMPT = """Analyze this first garment once and return JSON:
{
  "category": "apparel category",
  "garment_structure": {"neckline":"", "sleeve_type":"", "fit":"", "closure":"", "hem_type":""},
  "view_rules": {"supports_front":true, "supports_back":true, "front_back_must_not_swap":true},
  "design_rules": {"preserve_text":true, "preserve_numbers":true, "preserve_names":true, "preserve_graphics":true, "preserve_font_style":true, "preserve_element_position":true},
  "structure_rules": {"preserve_neckline":true, "preserve_sleeves":true, "preserve_garment_length":true, "preserve_silhouette":true},
  "observation": {"summary":"short factual structural observation"}
}"""


def build_template_analysis_prompt(*, mode: str, requested: dict[str, object]) -> str:
    detail = mode == "detail_tryon"
    return f"""Analyze this {'detail' if detail else 'model'} template once for virtual try-on.
Return only JSON with these fields:
{{
  "quality": "usable|limited|unusable",
  "body_view": "front|back|side|three_quarter|unknown",
  "crop_type": "full_body|three_quarter|half_body|upper_body|detail|unknown",
  "camera_angle": "short description",
  "camera_distance": "short description",
  "pose": "short description",
  "background": "short description",
  "lighting": "short description",
  "composition": "short description",
  "occlusion": ["regions hidden by hands, hair, props or crop"],
  "focus_area": "{requested.get('focus_area') or 'garment'}",
  "detail_priority": "{requested.get('detail_priority') or ''}",
  "visible_regions": {json.dumps(requested.get('visible_regions') or [], ensure_ascii=False)},
  "keep_original_crop": true,
  "keep_original_composition": true
}}
Do not invent product details. Preserve the template crop, zoom, camera distance, angle, body framing, pose, background, lighting and composition."""


def parse_analysis_text(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start:end + 1]
    try:
        value = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def normalize_garment_profile(value: dict[str, Any], *, source_asset_id: str, model_code: str) -> dict[str, object]:
    def record(key: str) -> dict[str, object]:
        raw = value.get(key)
        return raw if isinstance(raw, dict) else {}

    # Older or non-strict vision gateways sometimes return a useful nested
    # `reusable_structure_rules` object instead of the requested flat schema.
    # Preserve that analysis rather than silently presenting an empty profile.
    reusable = record("reusable_structure_rules")
    nested = reusable or value
    silhouette = nested.get("silhouette") if isinstance(nested.get("silhouette"), dict) else {}
    neckline = nested.get("neckline") if isinstance(nested.get("neckline"), dict) else {}
    sleeves = nested.get("sleeves") if isinstance(nested.get("sleeves"), dict) else {}
    structure = record("garment_structure")
    if not structure and any((silhouette, neckline, sleeves)):
        structure = {
            "neckline": _first_text(neckline, "type", "construction"),
            "sleeve_type": _first_text(sleeves, "type", "construction"),
            "fit": _first_text(silhouette, "fit", "body_shape"),
            "closure": _first_text(neckline, "front_opening"),
            "hem_type": _first_text(silhouette, "hem", "length"),
        }
        structure = {key: item for key, item in structure.items() if item}

    return {
        "profile_key": "first-garment-structure",
        "source_sample_asset_id": source_asset_id,
        "category": str(value.get("category") or value.get("garment_type") or "apparel")[:120],
        "garment_structure": structure,
        "view_rules": record("view_rules") or {
            "supports_front": True,
            "supports_back": True,
            "front_back_must_not_swap": True,
        },
        "design_rules": record("design_rules") or {
            "preserve_text": True,
            "preserve_numbers": True,
            "preserve_names": True,
            "preserve_graphics": True,
            "preserve_font_style": True,
            "preserve_element_position": True,
        },
        "structure_rules": record("structure_rules") or {
            "preserve_neckline": True,
            "preserve_sleeves": True,
            "preserve_garment_length": True,
            "preserve_silhouette": True,
        },
        "analysis_model": model_code,
        "analysis_version": "server-first-garment-v1",
        "observation": record("observation") or ({
            "legacy_reusable_structure_rules": reusable or {
                key: nested[key] for key in ("silhouette", "neckline", "sleeves") if key in nested
            },
        } if any((silhouette, neckline, sleeves)) else {}),
    }


def normalize_template_profile(value: dict[str, Any], *, requested: dict[str, object]) -> dict[str, object]:
    def text(key: str, fallback: str = "") -> str:
        return str(value.get(key) or requested.get(key) or fallback).strip()[:500]

    occlusion = value.get("occlusion") if isinstance(value.get("occlusion"), list) else []
    visible = value.get("visible_regions") if isinstance(value.get("visible_regions"), list) else requested.get("visible_regions") or []
    return {
        "quality": text("quality", "limited"),
        "body_view": text("body_view", "unknown"),
        "crop_type": text("crop_type", "unknown"),
        "camera_angle": text("camera_angle"),
        "camera_distance": text("camera_distance"),
        "pose": text("pose"),
        "background": text("background"),
        "lighting": text("lighting"),
        "composition": text("composition"),
        "occlusion": [str(item)[:120] for item in occlusion[:20]],
        "focus_area": text("focus_area", "garment"),
        "detail_priority": text("detail_priority"),
        "visible_regions": [str(item)[:120] for item in list(visible)[:20]],
        "keep_original_crop": value.get("keep_original_crop") is not False,
        "keep_original_composition": value.get("keep_original_composition") is not False,
    }


def validate_garment_profile(profile: dict[str, object]) -> None:
    structure = profile.get("garment_structure")
    populated = [item for item in structure.values() if str(item).strip()] if isinstance(structure, dict) else []
    if len(populated) < 2:
        raise AnalysisResultError(
            "batch_tryon.garment_analysis_invalid",
            "服装分析未返回有效的结构字段，请重试生成组合。",
        )


def validate_template_profile(profile: dict[str, object]) -> None:
    quality = str(profile.get("quality") or "").lower()
    body_view = str(profile.get("body_view") or "").lower()
    crop_type = str(profile.get("crop_type") or "").lower()
    if quality not in {"usable", "limited", "unusable"} or (
        body_view == "unknown" and crop_type == "unknown"
    ):
        raise AnalysisResultError(
            "batch_tryon.template_analysis_invalid",
            "模板分析未返回有效的构图结构，请重试生成组合。",
        )


class AnalysisResultError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _first_text(value: dict[str, Any], *keys: str) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()[:500]
    return ""

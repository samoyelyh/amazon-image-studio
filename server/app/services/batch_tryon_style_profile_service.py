from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tasks import BatchGarmentStyleProfile, Job, JobBatch


STRUCTURE_FIELDS = {"neckline", "sleeve_type", "fit", "closure", "hem_type"}
VIEW_RULE_FIELDS = {"supports_front", "supports_back", "front_back_must_not_swap"}
DESIGN_RULE_FIELDS = {
    "preserve_text", "preserve_numbers", "preserve_names", "preserve_graphics",
    "preserve_font_style", "preserve_element_position",
}
STRUCTURE_RULE_FIELDS = {
    "preserve_neckline", "preserve_sleeves", "preserve_garment_length", "preserve_silhouette",
}
FORBIDDEN_PROFILE_KEYS = {
    "main_color", "secondary_color", "specific_color_scheme", "specific_text", "specific_number",
    "specific_name", "specific_graphic_content", "specific_logo", "specific_team_name",
    "color", "colors", "text", "number", "name", "logo", "team_name", "graphic_content",
}
VARIABLE_VALUE_PATTERN = re.compile(
    r"(#[0-9a-f]{3,8}|\b(?:black|white|red|blue|green|yellow|orange|purple|pink|gray|grey|brown|gold|silver)\b|"
    r"颜色|黑色|白色|红色|蓝色|绿色|黄色|号码|姓名|队名|logo|graphic content)",
    re.IGNORECASE,
)


def sanitize_style_profile_snapshot(value: object) -> dict[str, object]:
    raw = _record(value)
    if any(str(key).lower() in FORBIDDEN_PROFILE_KEYS for key in raw):
        raw = {key: item for key, item in raw.items() if str(key).lower() not in FORBIDDEN_PROFILE_KEYS}
    structure = _string_fields(_record(raw.get("garment_structure")), STRUCTURE_FIELDS)
    view_rules = _bool_fields(_record(raw.get("view_rules")), VIEW_RULE_FIELDS, default=True)
    design_rules = _bool_fields(_record(raw.get("design_rules")), DESIGN_RULE_FIELDS, default=True)
    structure_rules = _bool_fields(_record(raw.get("structure_rules")), STRUCTURE_RULE_FIELDS, default=True)
    category = _safe_structure_value(raw.get("category"), "apparel")
    return {
        "profile_key": _safe_identifier(raw.get("profile_key"), "profile"),
        "source_sample_asset_id": str(raw.get("source_sample_asset_id") or "")[:36],
        "category": category,
        "garment_structure": structure,
        "view_rules": view_rules,
        "design_rules": design_rules,
        "structure_rules": structure_rules,
        "analysis_model": str(raw.get("analysis_model") or "")[:120],
        "analysis_version": str(raw.get("analysis_version") or "batch-style-v1")[:80],
    }


def sanitize_first_sample_observation(value: object) -> dict[str, object]:
    sanitized = _sanitize_debug_value(value, depth=0)
    return sanitized if isinstance(sanitized, dict) else {}


async def persist_batch_style_profiles(
    session: AsyncSession,
    *,
    batch: JobBatch,
    jobs: list[Job],
) -> list[BatchGarmentStyleProfile]:
    if batch.workspace_type != "batch_tryon":
        return []
    existing = {
        item.profile_key: item
        for item in (await session.scalars(select(BatchGarmentStyleProfile).where(
            BatchGarmentStyleProfile.batch_id == batch.id,
        ))).all()
    }
    assets_by_profile: dict[str, set[str]] = {}
    snapshots: dict[str, dict[str, object]] = {}
    observations: dict[str, dict[str, object]] = {}
    jobs_by_profile: dict[str, list[Job]] = {}
    for job in jobs:
        metadata = _record(job.input_json.get("metadata"))
        raw_snapshot = metadata.get("batch_style_profile")
        if not isinstance(raw_snapshot, dict):
            continue
        snapshot = sanitize_style_profile_snapshot(raw_snapshot)
        profile_key = str(snapshot["profile_key"])
        source_asset_id = str(snapshot["source_sample_asset_id"])
        garment_asset_id = str(metadata.get("garment_asset_id") or "")
        if not source_asset_id or not garment_asset_id:
            continue
        snapshots[profile_key] = snapshot
        observation = sanitize_first_sample_observation(metadata.get("first_sample_observation"))
        if observation:
            observations[profile_key] = observation
        assets_by_profile.setdefault(profile_key, set()).add(garment_asset_id)
        jobs_by_profile.setdefault(profile_key, []).append(job)

    profiles: list[BatchGarmentStyleProfile] = []
    for profile_key, snapshot in snapshots.items():
        profile = existing.get(profile_key)
        if profile is None:
            profile = BatchGarmentStyleProfile(
                organization_id=batch.organization_id,
                batch_id=batch.id,
                source_sample_asset_id=str(snapshot["source_sample_asset_id"]),
                profile_key=profile_key,
                category=str(snapshot["category"]),
                structure_json=_record(snapshot["garment_structure"]),
                view_rules_json=_record(snapshot["view_rules"]),
                preservation_rules_json={
                    "design_rules": _record(snapshot["design_rules"]),
                    "structure_rules": _record(snapshot["structure_rules"]),
                },
                covered_garment_asset_ids_json=sorted(assets_by_profile[profile_key]),
                first_sample_observation_json=observations.get(profile_key),
                analysis_model=str(snapshot["analysis_model"]) or None,
                analysis_version=str(snapshot["analysis_version"]),
                created_by=batch.created_by,
            )
            session.add(profile)
            await session.flush()
            existing[profile_key] = profile
        elif profile.first_sample_observation_json is None and profile_key in observations:
            profile.first_sample_observation_json = observations[profile_key]
        profiles.append(profile)
        for job in jobs_by_profile[profile_key]:
            payload = dict(job.input_json)
            metadata = dict(_record(payload.get("metadata")))
            metadata["batch_style_profile_id"] = profile.id
            metadata["batch_style_profile"] = snapshot
            payload["metadata"] = metadata
            job.input_json = payload
    return profiles


def _record(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_identifier(value: object, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "")).strip("-")[:80]
    return cleaned or fallback


def _safe_structure_value(value: object, fallback: str) -> str:
    text = str(value or "").strip()[:80]
    return fallback if not text or VARIABLE_VALUE_PATTERN.search(text) else text


def _string_fields(value: dict[str, Any], allowed: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in allowed:
        text = _safe_structure_value(value.get(key), "")
        if text:
            result[key] = text
    return result


def _bool_fields(value: dict[str, Any], allowed: set[str], *, default: bool) -> dict[str, bool]:
    return {key: value[key] if isinstance(value.get(key), bool) else default for key in allowed}


def _sanitize_debug_value(value: object, *, depth: int) -> object:
    if depth >= 4:
        return str(value)[:500]
    if isinstance(value, dict):
        return {
            str(key)[:80]: _sanitize_debug_value(item, depth=depth + 1)
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, list):
        return [_sanitize_debug_value(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:500]

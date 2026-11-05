"""Offline Strategy A experiment helper. Never imported by app routes or Workers.

There is deliberately no network runner, task queue, credential lookup, or
production entry point here. Tests supply the existing Provider with Mock HTTP
and reuse the real ORM/Asset/S3 services against SQLite and an in-memory S3 client.
Synthetic fixture images are NOT AI-generated acceptance samples.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.errors import AppError
from app.models.content import Asset, GeneratedOutput
from app.providers.base import ProviderError, ProviderResult
from app.services.asset_service import create_asset, validate_image


@dataclass(frozen=True)
class ChannelCapabilities:
    enabled: bool = False
    supports_n: bool = False
    supports_size: bool = False
    supports_quality: bool = False
    dimension_mode: str = "aspect_ratio"
    max_outputs: int = 1


def strategy_a_config(base: dict, capabilities: ChannelCapabilities, count: int = 4) -> dict:
    """A-only config COPY; declaring support is not evidence of upstream support."""
    if not capabilities.enabled or not capabilities.supports_n:
        raise ValueError("Strategy A is disabled or native n is not declared")
    if isinstance(count, bool) or not 1 <= count <= capabilities.max_outputs:
        raise ValueError("requested count exceeds the declared channel limit")
    if capabilities.dimension_mode not in {"size", "aspect_ratio"}:
        raise ValueError("choose one verified dimension protocol")
    if capabilities.dimension_mode == "size" and not capabilities.supports_size:
        raise ValueError("size protocol is not declared supported")
    result = deepcopy(base)
    result["image_api_mode"] = "images"
    result["edit_dimension_mode"] = capabilities.dimension_mode
    # Do not widen the provider/model config shared by B.
    fields = ["model", "prompt", "n", capabilities.dimension_mode]
    if capabilities.supports_quality:
        fields.append("quality")
    result["edit_body_fields"] = fields
    return result


def build_input(template: dict, garments: list[dict], *, size: str = "1536x2048") -> tuple[dict, dict, bytes]:
    """One unchanged template + one locally assembled four-garment input sheet."""
    if len(garments) != 4 or len({g["asset_id"] for g in garments}) != 4:
        raise ValueError("round 1 requires four distinct garment Asset IDs")
    sheet = Image.new("RGB", (1024, 1408), "#e5e7eb")
    draw = ImageDraw.Draw(sheet)
    panels = []
    for index, garment in enumerate(garments):
        x, y = (index % 2) * 512, (index // 2) * 704
        draw.rectangle((x + 8, y + 8, x + 504, y + 696), fill="white")
        draw.text((x + 20, y + 14), str(index + 1), fill="black")
        with Image.open(BytesIO(garment["content"])) as image:
            image.load()
            native_size = list(image.size)
            image = image.convert("RGB")
            image.thumbnail((472, 640), Image.Resampling.LANCZOS)
            left, top = x + (512 - image.width) // 2, y + 48 + (640 - image.height) // 2
            sheet.paste(image, (left, top))
        panels.append({
            "pair_id": f"{template['asset_id']}:{garment['asset_id']}",
            "template_asset_id": template["asset_id"], "garment_asset_id": garment["asset_id"],
            "source_filename": garment["filename"], "source_sha256": sha256(garment["content"]).hexdigest(),
            "source_native_size": native_size, "panel_number": index + 1,
            "panel_rect": [x / 1024, y / 1408, 0.5, 0.5],
            "artwork_rect": [left / 1024, top / 1408, image.width / 1024, image.height / 1408],
        })
    buffer = BytesIO()
    sheet.save(buffer, format="PNG")
    collage = buffer.getvalue()
    manifest = {
        "schema_version": 1, "strategy": "A", "expected_count": 4,
        "template_asset_id": template["asset_id"], "template_filename": template["filename"],
        "template_sha256": sha256(template["content"]).hexdigest(),
        "collage_sha256": sha256(collage).hexdigest(), "collage_size": [1024, 1408],
        "panels": panels, "output_mapping_status": "unverified",
    }
    prompt = (
        "Image A is ONE fixed complete template, not a sheet of templates. "
        "Image B is a numbered four-garment INPUT sheet. Generate exactly four separate, "
        "independently encoded full-frame try-on images, one for each garment panel. "
        "Use the same complete template A for every output. Preserve people, identities, poses, "
        "background, composition, lighting and captions. Replace only the target garment using "
        "the corresponding panel's actual design and structure. Never mix garments or keep old "
        "template clothing designs. Do not return a collage, contact sheet, panel labels or gutters. "
        f"Requested output size is {size}. Requested quality is high. "
        "Follow the input pair manifest; requested order is only a hint and will require review.\n"
        + json.dumps(panels, ensure_ascii=False)
    )
    return {
        "prompt": prompt, "n": 4, "size": size, "aspect_ratio": "3:4", "quality": "high",
        "reference_images": [
            {"filename": template["filename"], "mime_type": "image/png", "content": template["content"]},
            {"filename": "garment-collage.png", "mime_type": "image/png", "content": collage},
        ],
    }, manifest, collage


def observe(result: ProviderResult, settings, *, expected_count: int = 4, http_requests: int = 1) -> dict:
    entries, hashes = [], set()
    for index, output in enumerate(result.outputs):
        entry = {"sequence_number": index, "sha256": sha256(output.content).hexdigest(),
                 "byte_count": len(output.content), "mapping_status": "unverified"}
        try:
            mime, extension, width, height, _ = validate_image(
                output.content, None, settings, max_bytes=settings.provider_output_max_bytes,
            )
            # verify() alone does not fully decode every image format.
            with Image.open(BytesIO(output.content)) as image:
                image.load()
            entry.update(valid=True, mime_type=mime, extension=extension, width=width, height=height)
            entry["duplicate"] = entry["sha256"] in hashes
            hashes.add(entry["sha256"])
        except (AppError, OSError, ValueError) as error:
            entry.update(valid=False, error_code=getattr(error, "code", "image.decode_failed"))
        entries.append(entry)
    anomalies = []
    if len(entries) != expected_count:
        anomalies.append("output_count_mismatch")
    if any(not e["valid"] for e in entries):
        anomalies.append("invalid_image")
    if any(e.get("duplicate") for e in entries):
        anomalies.append("duplicate_image")
    valid = sum(e["valid"] for e in entries)
    return {
        "schema_version": 1, "strategy": "A", "expected_count": expected_count,
        "returned_count": len(entries), "valid_count": valid, "saved_count": 0,
        "http_request_count": http_requests,
        "image_generation_tool_call_count": (result.metadata or {}).get("image_generation_call_count"),
        "upstream_request_id": result.provider_request_id,
        "group_status": "complete" if not anomalies else ("partial" if valid else "failed"),
        "anomalies": anomalies, "entries": entries, "auto_retry_allowed": False,
        "mapping_status": "unverified", "billing_status": "awaiting_reconciliation",
        "upstream_actual_cost": None,
    }


def observe_error(error: ProviderError) -> dict:
    unknown = error.code in {"provider.timeout", "provider.network_error"} or error.http_status in {408, 524} or (
        error.http_status is not None and error.http_status >= 500
    )
    return {
        "schema_version": 1, "strategy": "A", "expected_count": 4,
        "returned_count": 0 if error.code == "provider.empty_result" else None,
        "valid_count": 0, "saved_count": 0, "http_request_count": 1,
        "image_generation_tool_call_count": None,
        "group_status": "remote_unknown" if unknown else "failed",
        "error_code": error.code, "http_status": error.http_status,
        "auto_retry_allowed": False, "billing_status": "awaiting_reconciliation",
        "upstream_actual_cost": None,
    }


async def persist_mock_outputs(session, storage, settings, *, job, result: ProviderResult, observation: dict) -> dict:
    """Exercise existing persistence, without Version creation or delivery resizing.

    Per-output durability and replay are part of this experiment, NOT the current
    production Worker's behavior. The request Job is created in the test fixture,
    because the current submission Schema intentionally still rejects n=4.
    """
    summary = deepcopy(observation)
    existing = {row.sequence_number: row for row in (await session.scalars(
        select(GeneratedOutput).where(GeneratedOutput.job_id == job.id)
    )).all()}
    for entry in summary["entries"]:
        index = entry["sequence_number"]
        output = result.outputs[index]
        if index in existing:
            asset = await session.get(Asset, existing[index].asset_id)
            if asset.sha256 != entry["sha256"]:
                raise ValueError("same Job/sequence cannot be replaced by different bytes")
            entry.update(asset_id=asset.id, storage_key=asset.storage_key)
            continue
        if not entry["valid"]:
            key = f"organizations/{job.organization_id}/strategy-a-quarantine/{job.id}/{uuid4().hex}.bin"
            storage.upload(key, output.content, content_type="application/octet-stream")
            entry["quarantine_storage_key"] = key
            continue
        try:
            asset = await create_asset(
                session, storage, settings, organization_id=job.organization_id, user_id=job.created_by,
                category="batch_tryon_output", filename=f"strategy-a-output-{index:03d}.{entry['extension']}",
                declared_mime=entry["mime_type"], data=output.content,
                max_bytes=settings.provider_output_max_bytes,
                metadata_json={"strategy": "A", "sequence_number": index, "mapping_status": "unverified"},
            )
        except AppError as error:
            entry["save_error_code"] = error.code
            summary["group_status"] = "partial"
            if "storage_save_failed" not in summary["anomalies"]:
                summary["anomalies"].append("storage_save_failed")
            continue
        row = GeneratedOutput(
            organization_id=job.organization_id, project_id=job.project_id, asset_id=asset.id, job_id=job.id,
            sequence_number=index, output_type="strategy_a_raw", metadata_json={
                "strategy": "A", "original_sequence_number": index, "mapping_status": "unverified",
            }, created_by=job.created_by, created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        entry.update(asset_id=asset.id, storage_key=asset.storage_key)
        existing[index] = row
        summary["saved_count"] = sum("asset_id" in item for item in summary["entries"])
        job.result_json = {"metadata": {"strategy_a": deepcopy(summary)}}
        await session.commit()
    summary["saved_count"] = sum("asset_id" in item for item in summary["entries"])
    job.result_json = {"metadata": {"strategy_a": summary}}
    await session.commit()
    return summary


def export_raw_results(storage, summary: dict, manifest: dict, collage: bytes) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("source/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("source/garment-collage.png", collage)
        archive.writestr("request-group.json", json.dumps(summary, ensure_ascii=False, indent=2))
        for entry in summary["entries"]:
            index = entry["sequence_number"]
            if entry.get("storage_key"):
                archive.writestr(f"outputs/output-{index:03d}.{entry['extension']}", storage.download(entry["storage_key"]))
            elif entry.get("quarantine_storage_key"):
                archive.writestr(f"quarantine/output-{index:03d}.bin", storage.download(entry["quarantine_storage_key"]))
    return buffer.getvalue()

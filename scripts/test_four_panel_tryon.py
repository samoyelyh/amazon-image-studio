#!/usr/bin/env python3
"""Real, queue-independent 2x2 virtual try-on diagnostics.

The script reads existing providers, encrypted keys, and assets, then calls the
configured New API image-edit endpoint directly. It never creates application
jobs, batches, quota records, generated assets, or Celery messages.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from math import gcd
from pathlib import Path
import re
from time import monotonic
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat, UnidentifiedImageError
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.content import Asset
from app.models.tasks import ApiKey, Job, JobBatch, Provider, ProviderModel
from app.providers.urls import provider_url
from app.security.api_keys import decrypt_api_key
from app.services.asset_service import read_asset_content
from app.services.storage_service import get_storage_service


UTC = timezone.utc
DEFAULT_SIZES = ("1024x1536", "2032x2704", "2496x3312")
BASE_WIDTH = 2496
BASE_HEIGHT = 3312
BASE_GAP_X = 48
BASE_GAP_Y = 48
BASE_PANEL_WIDTH = 1224
BASE_PANEL_HEIGHT = 1632
BASE_LAYOUT = {
    "top_left": [0, 0, 1224, 1632],
    "top_right": [1272, 0, 2496, 1632],
    "bottom_left": [0, 1680, 1224, 3312],
    "bottom_right": [1272, 1680, 2496, 3312],
}
POSITIONS = tuple(BASE_LAYOUT)
PROMPT = """Use the first input image as the fixed 2x2 model-template grid.

Use the second input image as the matching 2x2 garment-reference grid.

Perform four independent virtual try-on edits inside the existing grid.

Strict position mapping:

- Apply the top-left garment only to the top-left model.
- Apply the top-right garment only to the top-right model.
- Apply the bottom-left garment only to the bottom-left model.
- Apply the bottom-right garment only to the bottom-right model.

Do not mix garment details between panels.

Keep the exact canvas size, 2x2 layout, panel positions, separator positions and panel proportions unchanged.

In every panel, preserve the original model identity, face, hairstyle, pose, body proportions, camera angle, framing, background and lighting.

Only replace the upper garment.

Preserve each corresponding garment's exact colors, graphics, text, numbers, stripes, neckline, sleeves, hem, silhouette and fabric appearance.

Do not redesign the clothing.

Do not create one scene with four people.
Do not create a poster, free-form collage or contact sheet.
Do not overlap content across panels.
Do not remove or move the separators.

Return one single fixed 2x2 grid image containing four independent try-on results."""
SAFE_HEADERS = ("content-type", "server", "cf-ray", "x-request-id", "retry-after")


@dataclass
class ProviderFixture:
    id: str
    code: str
    name: str
    base_url: str
    provider_type: str
    model_id: str
    upstream_model: str
    key_id: str
    key_label: str
    key_status: str
    api_key: str
    config: dict[str, object]


@dataclass
class AssetFixture:
    id: str
    category: str
    filename: str
    masked_filename: str
    width: int
    height: int
    mime_type: str
    content: bytes


@dataclass
class TestResult:
    provider_id: str
    provider_code: str
    provider_name: str
    endpoint: str
    model: str
    request_size: str
    request_aspect_ratio: str
    quality: str
    output_format: str
    input_image_count: int
    prompt_length: int
    request_started_at: str
    response_finished_at: str
    duration_ms: int
    http_status: int | None
    response_content_type: str | None
    server: str | None
    cf_ray: str | None
    upstream_request_id: str | None
    retry_after: str | None
    error_type: str | None
    error_code: str | None
    error_message: str | None
    requested_width: int
    requested_height: int
    actual_width: int | None
    actual_height: int | None
    size_match: bool | None
    result_level: str
    result_file: str | None
    crop_mode: str | None
    crop_size: str | None
    crop_files: list[str]
    final_files: list[str]
    final_transform: str | None
    crop_valid: bool | None
    visual_review: dict[str, str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", action="append", dest="providers")
    parser.add_argument("--model-code", default="gpt-image-2")
    parser.add_argument("--size", action="append", dest="sizes")
    parser.add_argument("--template-asset-id")
    parser.add_argument("--garment-asset-id", action="append", dest="garment_asset_ids")
    parser.add_argument("--prepare-candidates", action="store_true")
    parser.add_argument("--build-inputs-only", action="store_true")
    parser.add_argument("--candidate-limit", type=int, default=24)
    parser.add_argument("--output-root", default="diagnostics/four-panel-tryon")
    parser.add_argument("--connect-timeout", type=float, default=30.0)
    parser.add_argument("--read-timeout", type=float, default=600.0)
    return parser.parse_args()


def dump_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def mask_filename(filename: str) -> str:
    path = Path(filename)
    stem = path.stem
    if len(stem) <= 2:
        masked = f"{stem[:1]}***"
    elif len(stem) <= 6:
        masked = f"{stem[:1]}***{stem[-1:]}"
    else:
        masked = f"{stem[:3]}***{stem[-3:]}"
    return f"{masked}{path.suffix.lower()}"


def mask_key(secret: str) -> str:
    if len(secret) < 8:
        return "****"
    return f"{secret[:4]}****{secret[-4:]}"


def safe_text(value: object, secrets: list[str]) -> str:
    text = str(value or "").replace("\x00", "")[:2000]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def parse_size(size: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", size.lower())
    if not match:
        raise ValueError(f"invalid size: {size}")
    return int(match.group(1)), int(match.group(2))


def aspect_ratio(size: str) -> str:
    width, height = parse_size(size)
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def image_from_bytes(content: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(content)) as source:
            source.load()
            return ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise RuntimeError("Asset is not a readable image") from error


async def load_providers(
    session: AsyncSession,
    selectors: list[str],
    model_code: str,
) -> list[ProviderFixture]:
    settings = get_settings()
    providers = list((await session.scalars(select(Provider).where(
        Provider.enabled.is_(True),
        Provider.id.in_(selectors) | Provider.code.in_(selectors),
    ))).all())
    fixtures: list[ProviderFixture] = []
    for provider in providers:
        model = await session.scalar(select(ProviderModel).where(
            ProviderModel.provider_id == provider.id,
            ProviderModel.code == model_code,
            ProviderModel.enabled.is_(True),
        ))
        if model is None:
            raise RuntimeError(f"{provider.code}: enabled model {model_code!r} not found")
        key = await session.scalar(
            select(ApiKey)
            .where(
                ApiKey.provider_id == provider.id,
                ApiKey.enabled.is_(True),
                ApiKey.status != "disabled",
            )
            .order_by(case((ApiKey.status == "active", 0), else_=1), ApiKey.created_at.desc())
            .limit(1)
        )
        if key is None:
            raise RuntimeError(f"{provider.code}: no enabled key")
        fixtures.append(ProviderFixture(
            id=provider.id,
            code=provider.code,
            name=provider.name,
            base_url=provider.base_url,
            provider_type=provider.provider_type,
            model_id=model.id,
            upstream_model=model.upstream_model,
            key_id=key.id,
            key_label=key.label,
            key_status=key.status,
            api_key=decrypt_api_key(settings, key.secret_ciphertext),
            config={**(provider.config_json or {}), **(model.config_json or {})},
        ))
    order = {selector: index for index, selector in enumerate(selectors)}
    fixtures.sort(key=lambda fixture: min(order.get(fixture.id, 9999), order.get(fixture.code, 9999)))
    missing = [selector for selector in selectors if not any(selector in {item.id, item.code} for item in fixtures)]
    if missing:
        raise RuntimeError(f"Provider not found: {', '.join(missing)}")
    return fixtures


async def load_assets(
    session: AsyncSession,
    asset_ids: list[str],
) -> list[AssetFixture]:
    assets = list((await session.scalars(select(Asset).where(
        Asset.id.in_(asset_ids),
        Asset.deleted_at.is_(None),
    ))).all())
    by_id = {asset.id: asset for asset in assets}
    missing = [asset_id for asset_id in asset_ids if asset_id not in by_id]
    if missing:
        raise RuntimeError(f"Asset not found: {', '.join(missing)}")
    result: list[AssetFixture] = []
    storage = get_storage_service()
    for asset_id in asset_ids:
        asset = by_id[asset_id]
        result.append(AssetFixture(
            id=asset.id,
            category=asset.category,
            filename=asset.filename,
            masked_filename=mask_filename(asset.filename),
            width=asset.width,
            height=asset.height,
            mime_type=asset.mime_type,
            content=await read_asset_content(asset, storage),
        ))
    return result


async def state_snapshot(session: AsyncSession) -> dict[str, object]:
    statuses = (await session.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status).order_by(Job.status)
    )).all()
    return {
        "jobs_total": int(await session.scalar(select(func.count(Job.id))) or 0),
        "job_batches_total": int(await session.scalar(select(func.count(JobBatch.id))) or 0),
        "assets_total": int(await session.scalar(select(func.count(Asset.id))) or 0),
        "job_status_counts": {str(status): int(count) for status, count in statuses},
    }


def candidate_contact_sheet(
    assets: list[AssetFixture],
    destination: Path,
) -> None:
    cell_width, cell_height = 320, 390
    columns = 4
    rows = max(1, (len(assets) + columns - 1) // columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, asset in enumerate(assets):
        image = ImageOps.contain(image_from_bytes(asset.content), (cell_width - 24, cell_height - 70))
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        image_x = x + (cell_width - image.width) // 2
        image_y = y + 8
        sheet.paste(image, (image_x, image_y))
        label = f"{index + 1:02d}  {asset.id[:8]}  {asset.width}x{asset.height}"
        draw.text((x + 10, y + cell_height - 50), label, fill="black", font=font)
        draw.text((x + 10, y + cell_height - 30), asset.masked_filename, fill="black", font=font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, optimize=True)


async def prepare_candidates(
    session: AsyncSession,
    run_dir: Path,
    limit: int,
) -> None:
    manifest: dict[str, list[dict[str, object]]] = {}
    for category in ("model_template", "garment"):
        rows = list((await session.scalars(
            select(Asset)
            .where(Asset.category == category, Asset.deleted_at.is_(None))
            .order_by(Asset.created_at.desc())
            .limit(limit * 3)
        )).all())
        unique: list[Asset] = []
        hashes: set[str] = set()
        for asset in rows:
            if asset.sha256 in hashes:
                continue
            hashes.add(asset.sha256)
            unique.append(asset)
            if len(unique) >= limit:
                break
        fixtures = await load_assets(session, [asset.id for asset in unique])
        manifest[category] = [{
            "index": index,
            "asset_id": item.id,
            "masked_filename": item.masked_filename,
            "width": item.width,
            "height": item.height,
        } for index, item in enumerate(fixtures, start=1)]
        candidate_contact_sheet(fixtures, run_dir / f"{category}-candidates.png")
    dump_json(run_dir / "candidate-manifest.json", manifest)


def fit_template(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, (235, 235, 235))
    contained = ImageOps.contain(source, size, Image.Resampling.LANCZOS)
    canvas.paste(contained, ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2))
    return canvas


def fit_garment(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    margin = max(24, round(min(size) * 0.04))
    inner = (size[0] - margin * 2, size[1] - margin * 2)
    canvas = Image.new("RGB", size, (242, 242, 242))
    contained = ImageOps.contain(source, inner, Image.Resampling.LANCZOS)
    canvas.paste(contained, ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2))
    return canvas


def build_panels(
    template: AssetFixture,
    garments: list[AssetFixture],
    inputs_dir: Path,
) -> tuple[Path, Path]:
    inputs_dir.mkdir(parents=True, exist_ok=True)
    template_original = image_from_bytes(template.content)
    template_original.save(inputs_dir / "template-original.png", optimize=True)
    garment_images = []
    for index, garment in enumerate(garments, start=1):
        image = image_from_bytes(garment.content)
        image.save(inputs_dir / f"garment-{index}.png", optimize=True)
        garment_images.append(image)

    template_panel = Image.new("RGB", (BASE_WIDTH, BASE_HEIGHT), (224, 224, 224))
    garment_panel = Image.new("RGB", (BASE_WIDTH, BASE_HEIGHT), (224, 224, 224))
    template_cell = fit_template(template_original, (BASE_PANEL_WIDTH, BASE_PANEL_HEIGHT))
    for index, position in enumerate(POSITIONS):
        left, top, _, _ = BASE_LAYOUT[position]
        template_panel.paste(template_cell, (left, top))
        garment_panel.paste(
            fit_garment(garment_images[index], (BASE_PANEL_WIDTH, BASE_PANEL_HEIGHT)),
            (left, top),
        )
    template_path = inputs_dir / "template-panel.png"
    garment_path = inputs_dir / "garment-panel.png"
    template_panel.save(template_path, optimize=True)
    garment_panel.save(garment_path, optimize=True)
    return template_path, garment_path


def sanitized_response(body: object) -> object:
    if not isinstance(body, dict):
        return body
    cleaned = dict(body)
    data = cleaned.get("data")
    if isinstance(data, list):
        safe_items = []
        for item in data:
            if not isinstance(item, dict):
                safe_items.append(item)
                continue
            safe_item = dict(item)
            if safe_item.get("b64_json"):
                raw = str(safe_item["b64_json"])
                try:
                    decoded = base64.b64decode(raw, validate=True)
                    safe_item["b64_json"] = (
                        f"<omitted bytes={len(decoded)} sha256={sha256(decoded).hexdigest()}>"
                    )
                except ValueError:
                    safe_item["b64_json"] = "<invalid-base64-omitted>"
            safe_items.append(safe_item)
        cleaned["data"] = safe_items
    return cleaned


async def response_image(client: httpx.AsyncClient, item: dict[str, Any]) -> bytes:
    if item.get("b64_json"):
        return base64.b64decode(str(item["b64_json"]), validate=True)
    url = str(item.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("response did not contain an image")
    response = await client.get(url, follow_redirects=False)
    response.raise_for_status()
    return response.content


def classify_error(status: int, message: str) -> tuple[str, str]:
    lowered = message.lower()
    if status == 524 or "timeout" in lowered:
        return "TIMEOUT", "http_timeout"
    if status in {400, 422}:
        return "REJECTED_NEWAPI", "invalid_request"
    if status in {401, 403}:
        return "REJECTED_NEWAPI", "authentication_failed"
    if status == 429:
        return "REJECTED_NEWAPI", "rate_limited"
    if status >= 500:
        return "REJECTED_UPSTREAM", "upstream_5xx"
    return "UNSUPPORTED", "http_error"


def crop_and_deliver(
    result_path: Path,
    case_dir: Path,
) -> tuple[str, str, list[str], list[str], str, bool]:
    crops_dir = case_dir / "crops"
    final_dir = case_dir / "final-1350x1800"
    crops_dir.mkdir(exist_ok=True)
    final_dir.mkdir(exist_ok=True)
    crop_files: list[str] = []
    final_files: list[str] = []
    sizes: set[tuple[int, int]] = set()
    transforms: set[str] = set()
    valid = True
    with Image.open(result_path) as opened:
        source = ImageOps.exif_transpose(opened).convert("RGB")
        scale_x = source.width / BASE_WIDTH
        scale_y = source.height / BASE_HEIGHT
        mode = (
            "exact_layout_coordinates"
            if source.size == (BASE_WIDTH, BASE_HEIGHT)
            else "proportional_layout_coordinates"
        )
        for index, position in enumerate(POSITIONS, start=1):
            box = BASE_LAYOUT[position]
            scaled = (
                round(box[0] * scale_x),
                round(box[1] * scale_y),
                round(box[2] * scale_x),
                round(box[3] * scale_y),
            )
            crop = source.crop(scaled)
            sizes.add(crop.size)
            valid = valid and crop.width > 0 and crop.height > 0 and sum(ImageStat.Stat(crop).var) > 1
            crop_path = crops_dir / f"panel-{index}-{position.replace('_', '-')}.png"
            crop.save(crop_path, optimize=True)
            crop_files.append(str(crop_path))

            target_ratio = 3 / 4
            crop_ratio = crop.width / crop.height
            if abs(crop_ratio - target_ratio) / target_ratio <= 0.002:
                delivered = crop.resize((1350, 1800), Image.Resampling.LANCZOS)
                transform = "resize_no_crop"
            else:
                contained = ImageOps.contain(crop, (1350, 1800), Image.Resampling.LANCZOS)
                delivered = Image.new("RGB", (1350, 1800), (242, 242, 242))
                delivered.paste(
                    contained,
                    ((1350 - contained.width) // 2, (1800 - contained.height) // 2),
                )
                transform = "contain_neutral_padding"
            transforms.add(transform)
            final_path = final_dir / f"panel-{index}-final-1350x1800.png"
            delivered.save(final_path, optimize=True)
            final_files.append(str(final_path))
    crop_size = (
        f"{next(iter(sizes))[0]}x{next(iter(sizes))[1]}"
        if len(sizes) == 1 else "mixed"
    )
    return mode, crop_size, crop_files, final_files, ",".join(sorted(transforms)), bool(valid and len(sizes) == 1)


async def run_case(
    provider: ProviderFixture,
    requested_size: str,
    template_panel: Path,
    garment_panel: Path,
    run_dir: Path,
    connect_timeout: float,
    read_timeout: float,
) -> TestResult:
    width, height = parse_size(requested_size)
    ratio = aspect_ratio(requested_size)
    node_dir = run_dir / provider.code / requested_size
    node_dir.mkdir(parents=True, exist_ok=True)
    endpoint = str(provider.config.get("edits_endpoint") or "/images/edits")
    url = provider_url(provider.base_url, endpoint)
    request_summary = {
        "provider_id": provider.id,
        "provider_code": provider.code,
        "provider_name": provider.name,
        "base_url": provider.base_url,
        "api_key": mask_key(provider.api_key),
        "key_id": provider.key_id,
        "key_label": provider.key_label,
        "key_status_at_start": provider.key_status,
        "model": provider.upstream_model,
        "endpoint": url,
        "size": requested_size,
        "aspect_ratio": ratio,
        "quality": "high",
        "output_format": "png",
        "n": 1,
        "response_format": "b64_json",
        "input_image_count": 2,
        "input_fields": ["image", "image"],
        "prompt_length": len(PROMPT),
        "prompt_sha256": sha256(PROMPT.encode("utf-8")).hexdigest(),
        "authorization": "<redacted>",
    }
    dump_json(node_dir / "request-summary.json", request_summary)
    timeout = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=min(180.0, read_timeout),
        pool=connect_timeout,
    )
    start_dt = datetime.now(UTC)
    start = monotonic()
    finish_dt = start_dt
    status = None
    response_type = None
    response_headers: dict[str, str] = {}
    error_type = error_code = error_message = None
    actual_width = actual_height = None
    size_match = None
    result_level = "UNSUPPORTED"
    result_file: Path | None = None
    crop_mode = crop_size = final_transform = None
    crop_files: list[str] = []
    final_files: list[str] = []
    crop_valid = None
    secrets = [provider.api_key]
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            files = [
                ("image", ("template-panel.png", template_panel.read_bytes(), "image/png")),
                ("image", ("garment-panel.png", garment_panel.read_bytes(), "image/png")),
            ]
            data = {
                "model": provider.upstream_model,
                "prompt": PROMPT,
                "size": requested_size,
                "aspect_ratio": ratio,
                "quality": "high",
                "output_format": "png",
                "n": "1",
                "response_format": "b64_json",
            }
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {provider.api_key}"},
                data=data,
                files=files,
            )
            finish_dt = datetime.now(UTC)
            status = response.status_code
            response_type = response.headers.get("content-type")
            response_headers = {
                name: response.headers[name]
                for name in SAFE_HEADERS if name in response.headers
            }
            dump_json(node_dir / "response-headers.json", response_headers)
            try:
                body = response.json()
                dump_json(node_dir / "response.json", sanitized_response(body))
            except ValueError:
                body = None
                (node_dir / "response-body.txt").write_text(
                    safe_text(response.text, secrets),
                    encoding="utf-8",
                )
            if response.status_code >= 400:
                message = safe_text(body or response.text, secrets)
                result_level, error_code = classify_error(response.status_code, message)
                error_type = "http_error"
                error_message = message
            elif not isinstance(body, dict) or not isinstance(body.get("data"), list) or not body["data"]:
                error_type = "invalid_response"
                error_code = "empty_response"
                error_message = "Upstream response did not contain image data"
            else:
                content = await response_image(client, body["data"][0])
                result_file = node_dir / "result.png"
                result_file.write_bytes(content)
                with Image.open(result_file) as image:
                    actual_width, actual_height = image.size
                size_match = (actual_width, actual_height) == (width, height)
                result_level = "SUPPORTED_EXACT" if size_match else "SIZE_DOWNGRADED"
                (
                    crop_mode,
                    crop_size,
                    crop_files,
                    final_files,
                    final_transform,
                    crop_valid,
                ) = crop_and_deliver(result_file, node_dir)
    except httpx.TimeoutException as error:
        finish_dt = datetime.now(UTC)
        error_type = type(error).__name__
        error_code = "read_timeout"
        error_message = safe_text(error, secrets)
        result_level = "TIMEOUT"
    except (httpx.HTTPError, OSError, ValueError, RuntimeError) as error:
        finish_dt = datetime.now(UTC)
        error_type = type(error).__name__
        error_code = "diagnostic_error"
        error_message = safe_text(error, secrets)
        result_level = "UNSUPPORTED"

    return TestResult(
        provider_id=provider.id,
        provider_code=provider.code,
        provider_name=provider.name,
        endpoint=url,
        model=provider.upstream_model,
        request_size=requested_size,
        request_aspect_ratio=ratio,
        quality="high",
        output_format="png",
        input_image_count=2,
        prompt_length=len(PROMPT),
        request_started_at=start_dt.isoformat(),
        response_finished_at=finish_dt.isoformat(),
        duration_ms=max(0, round((monotonic() - start) * 1000)),
        http_status=status,
        response_content_type=response_type,
        server=response_headers.get("server"),
        cf_ray=response_headers.get("cf-ray"),
        upstream_request_id=response_headers.get("x-request-id"),
        retry_after=response_headers.get("retry-after"),
        error_type=error_type,
        error_code=error_code,
        error_message=error_message,
        requested_width=width,
        requested_height=height,
        actual_width=actual_width,
        actual_height=actual_height,
        size_match=size_match,
        result_level=result_level,
        result_file=str(result_file) if result_file else None,
        crop_mode=crop_mode,
        crop_size=crop_size,
        crop_files=crop_files,
        final_files=final_files,
        final_transform=final_transform,
        crop_valid=crop_valid,
        visual_review={
            "layout_preserved": "PENDING_MANUAL_REVIEW",
            "four_panels": "PENDING_MANUAL_REVIEW",
            "garment_mapping": "PENDING_MANUAL_REVIEW",
            "garment_cross_mix": "PENDING_MANUAL_REVIEW",
            "model_identity": "PENDING_MANUAL_REVIEW",
            "pose": "PENDING_MANUAL_REVIEW",
            "background": "PENDING_MANUAL_REVIEW",
            "garment_text": "PENDING_MANUAL_REVIEW",
            "garment_numbers": "PENDING_MANUAL_REVIEW",
            "garment_graphics": "PENDING_MANUAL_REVIEW",
            "crop_usability": "PENDING_MANUAL_REVIEW",
            "upscaled_usability": "PENDING_MANUAL_REVIEW",
        },
    )


def report_markdown(
    providers: list[ProviderFixture],
    template: AssetFixture,
    garments: list[AssetFixture],
    results: list[TestResult],
    run_dir: Path,
    before: dict[str, object],
    after: dict[str, object],
) -> str:
    lines = [
        "# 四合一批量换衣真实实例测试",
        "",
        f"- 模型：`{providers[0].upstream_model}`",
        "- 正式图片编辑端点：`/v1/images/edits`",
        "- 请求方式：multipart/form-data，两个重复 `image` 字段。",
        "- 测试方式：独立诊断直连，不创建正式 Job、批次、额度或 Celery 消息。",
        "",
        "## 素材",
        "",
        f"- 模板：`{template.id}` / `{template.masked_filename}` / {template.width}×{template.height}",
    ]
    for index, garment in enumerate(garments, start=1):
        lines.append(
            f"- 服装 {index}：`{garment.id}` / `{garment.masked_filename}` / "
            f"{garment.width}×{garment.height}"
        )
    lines += [
        "",
        "## 结果",
        "",
        "| New API | 请求尺寸 | HTTP | 实际尺寸 | 耗时 | 裁片 | 尺寸等级 | 视觉评分 |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for result in results:
        actual = (
            f"{result.actual_width}×{result.actual_height}"
            if result.actual_width and result.actual_height else "—"
        )
        visual = result.visual_review.get("overall", "PENDING_MANUAL_REVIEW")
        lines.append(
            f"| {result.provider_code} | {result.request_size.replace('x', '×')} "
            f"| {result.http_status or '—'} | {actual} | {result.duration_ms / 1000:.1f}s "
            f"| {result.crop_size or '—'} | {result.result_level} | {visual} |"
        )
    lines += [
        "",
        "## 队列隔离",
        "",
        f"- 测试前：`{json.dumps(before, ensure_ascii=False)}`",
        f"- 测试后：`{json.dumps(after, ensure_ascii=False)}`",
        "",
        f"- 结构化结果：`{run_dir / 'report.json'}`",
        "- 视觉评分需结合保存的原图、四张裁片和 1350×1800 文件人工复核后补充。",
    ]
    return "\n".join(lines) + "\n"


async def main() -> int:
    args = parse_args()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.output_root).resolve() / timestamp
    run_dir.mkdir(parents=True)
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)

    if args.prepare_candidates:
        async with session_factory() as session:
            await prepare_candidates(session, run_dir, args.candidate_limit)
        print(f"CANDIDATE_DIR={run_dir}", flush=True)
        return 0

    providers = args.providers or ["aso8ty-openai", "aso8ty-openai-channel-2"]
    sizes = args.sizes or list(DEFAULT_SIZES)
    if not args.template_asset_id:
        raise SystemExit("--template-asset-id is required")
    if not args.garment_asset_ids or len(args.garment_asset_ids) != 4:
        raise SystemExit("Pass exactly four --garment-asset-id values")

    async with session_factory() as session:
        provider_fixtures = await load_providers(session, providers, args.model_code)
        assets = await load_assets(
            session,
            [args.template_asset_id, *args.garment_asset_ids],
        )
        before = await state_snapshot(session)
    template, garments = assets[0], assets[1:]
    if template.category != "model_template":
        raise SystemExit(f"Template asset category is {template.category}, expected model_template")
    if any(item.category != "garment" for item in garments):
        raise SystemExit("All four garment assets must have category=garment")

    inputs_dir = run_dir / "inputs"
    template_panel, garment_panel = build_panels(template, garments, inputs_dir)
    dump_json(run_dir / "template-panel-layout.json", {
        "canvas": {"width": BASE_WIDTH, "height": BASE_HEIGHT},
        "separator": {"horizontal": BASE_GAP_Y, "vertical": BASE_GAP_X},
        "panel_size": {"width": BASE_PANEL_WIDTH, "height": BASE_PANEL_HEIGHT},
        "positions": BASE_LAYOUT,
        "template_asset_id": template.id,
        "template_masked_filename": template.masked_filename,
    })
    dump_json(run_dir / "garment-panel-layout.json", {
        "canvas": {"width": BASE_WIDTH, "height": BASE_HEIGHT},
        "positions": {
            position: {
                "garment_asset_id": garments[index].id,
                "masked_filename": garments[index].masked_filename,
                "box": BASE_LAYOUT[position],
            }
            for index, position in enumerate(POSITIONS)
        },
    })
    dump_json(run_dir / "environment.json", {
        "model": args.model_code,
        "connect_timeout": args.connect_timeout,
        "read_timeout": args.read_timeout,
        "production_connect_timeout": get_settings().provider_connect_timeout_seconds,
        "production_read_timeout": get_settings().provider_request_timeout_seconds,
        "production_job_timeout": get_settings().job_timeout_seconds,
        "providers": [{
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "base_url": item.base_url,
            "provider_type": item.provider_type,
            "model_id": item.model_id,
            "upstream_model": item.upstream_model,
            "key_id": item.key_id,
            "key_label": item.key_label,
            "key_status": item.key_status,
            "api_key": mask_key(item.api_key),
            "edits_endpoint": item.config.get("edits_endpoint", "/images/edits"),
        } for item in provider_fixtures],
        "state_before": before,
    })
    if args.build_inputs_only:
        print(f"INPUT_DIR={run_dir}", flush=True)
        return 0

    results: list[TestResult] = []
    for provider in provider_fixtures:
        for size in sizes:
            result = await run_case(
                provider,
                size,
                template_panel,
                garment_panel,
                run_dir,
                args.connect_timeout,
                args.read_timeout,
            )
            results.append(result)
            dump_json(run_dir / "report.json", [asdict(item) for item in results])
            print(
                f"{provider.code} {size}: {result.result_level} HTTP={result.http_status} "
                f"actual={result.actual_width}x{result.actual_height} "
                f"crop={result.crop_size} duration={result.duration_ms}ms",
                flush=True,
            )

    async with session_factory() as session:
        after = await state_snapshot(session)
    environment = json.loads((run_dir / "environment.json").read_text(encoding="utf-8"))
    environment["state_after"] = after
    dump_json(run_dir / "environment.json", environment)
    (run_dir / "report.md").write_text(
        report_markdown(provider_fixtures, template, garments, results, run_dir, before, after),
        encoding="utf-8",
    )
    print(f"REPORT_DIR={run_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

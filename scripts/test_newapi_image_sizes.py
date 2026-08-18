#!/usr/bin/env python3
"""Direct, non-production GPT image size diagnostics for configured New API nodes.

The script reads existing provider/model/API-key records, but never creates a
Job, quota reservation, asset, project version, or Celery message. Run it from
the backend container so it uses the same database, encryption key, and object
storage configuration as the application.
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
from pathlib import Path
import re
from time import monotonic
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageStat, UnidentifiedImageError
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.content import Asset
from app.models.tasks import ApiKey, Provider, ProviderModel
from app.providers.urls import provider_url
from app.security.api_keys import decrypt_api_key
from app.services.asset_service import read_asset_content
from app.services.image_size_service import (
    ImageSizeError,
    normalize_image_job_input,
    provider_dimension_fields,
    validate_submission_dimensions,
)
from app.services.storage_service import get_storage_service


UTC = timezone.utc
DEFAULT_SIZES = ("1024x1536", "1536x2048", "2032x2704", "2496x3312")
FIXED_SIZES = ("1024x1024", "1536x1024", "1024x1536", "auto")
GENERATION_PROMPT = """Create a clean 2x2 grid test image.

Keep four equal rectangular panels with clear separators.
Use a different solid background pattern in each panel:
top-left, top-right, bottom-left, bottom-right.

Do not add text.
Do not merge the panels.
Keep the grid geometry precise and symmetrical."""
EDIT_PROMPT = """Keep the exact 2x2 grid layout, canvas structure, separator positions,
panel dimensions and panel order unchanged.

Preserve the same model identity, face, hairstyle, pose, body proportions,
camera angle, framing, background and lighting in all four panels.

Make only a small visible color adjustment to the upper garment in each panel:
top-left red, top-right blue, bottom-left green, bottom-right black.

Do not merge panels.
Do not create a poster or free-form collage.
Do not move or remove separators.
Return one single 2x2 grid image."""
SAFE_RESPONSE_HEADERS = (
    "content-type",
    "server",
    "cf-ray",
    "x-request-id",
    "retry-after",
)


@dataclass
class ProviderFixture:
    id: str
    code: str
    name: str
    base_url: str
    provider_type: str
    model_id: str
    model_code: str
    upstream_model: str
    key_id: str
    key_label: str
    key_status: str
    api_key: str
    config: dict[str, object]


@dataclass
class TestResult:
    test_id: str
    provider_id: str
    provider_code: str
    provider_name: str
    endpoint: str
    endpoint_url: str
    model: str
    request_size: str
    request_aspect_ratio: str
    repeat: int
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
    requested_width: int | None
    requested_height: int | None
    actual_width: int | None
    actual_height: int | None
    size_match: bool | None
    result_level: str
    result_file: str | None
    request_file: str
    response_file: str | None
    adapter_dimension_field: str | None
    adapter_dimension_value: str | None
    adapter_request_body: dict[str, object] | None
    adapter_preflight_error: str | None
    crop_mode: str | None
    crop_files: list[str]
    crop_size: str | None
    crop_valid: bool | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider",
        action="append",
        dest="providers",
        help="Provider ID or code. Repeat for both New API nodes.",
    )
    parser.add_argument("--model-code", default="gpt-image-2")
    parser.add_argument("--endpoint", action="append", choices=("generations", "edits"))
    parser.add_argument("--size", action="append", dest="sizes")
    parser.add_argument("--include-fixed-sizes", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--template-asset-id")
    parser.add_argument("--output-root", default="diagnostics/newapi-image-size-test")
    parser.add_argument(
        "--refresh-report-dir",
        help="Rebuild adapter previews and reports from an existing diagnostic directory without new upstream calls.",
    )
    parser.add_argument("--connect-timeout", type=float, default=30.0)
    parser.add_argument("--read-timeout", type=float, default=600.0)
    return parser.parse_args()


def parse_size(size: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"(\d+)x(\d+)", size.lower())
    return (int(match.group(1)), int(match.group(2))) if match else (None, None)


def aspect_ratio(size: str) -> str:
    width, height = parse_size(size)
    if not width or not height:
        return "auto"
    from math import gcd
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def dump_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def safe_error(value: object, secrets: list[str]) -> str:
    text = str(value or "").replace("\x00", "")[:2000]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


async def load_fixtures(
    session: AsyncSession,
    provider_selectors: list[str],
    model_code: str,
) -> list[ProviderFixture]:
    settings = get_settings()
    providers = list((await session.scalars(
        select(Provider).where(
            Provider.enabled.is_(True),
            (Provider.id.in_(provider_selectors) | Provider.code.in_(provider_selectors)),
        )
    )).all())
    fixtures: list[ProviderFixture] = []
    for provider in providers:
        model = await session.scalar(select(ProviderModel).where(
            ProviderModel.provider_id == provider.id,
            ProviderModel.code == model_code,
            ProviderModel.enabled.is_(True),
        ))
        if model is None:
            raise RuntimeError(f"{provider.code}: enabled model {model_code!r} was not found")
        key = await session.scalar(
            select(ApiKey)
            .where(
                ApiKey.provider_id == provider.id,
                ApiKey.enabled.is_(True),
                ApiKey.status != "disabled",
            )
            .order_by(
                case((ApiKey.status == "active", 0), else_=1),
                ApiKey.created_at.desc(),
            )
            .limit(1)
        )
        if key is None:
            raise RuntimeError(f"{provider.code}: no enabled API key")
        fixtures.append(ProviderFixture(
            id=provider.id,
            code=provider.code,
            name=provider.name,
            base_url=provider.base_url,
            provider_type=provider.provider_type,
            model_id=model.id,
            model_code=model.code,
            upstream_model=model.upstream_model,
            key_id=key.id,
            key_label=key.label,
            key_status=key.status,
            api_key=decrypt_api_key(settings, key.secret_ciphertext),
            config={**(provider.config_json or {}), **(model.config_json or {})},
        ))
    ordered = {selector: index for index, selector in enumerate(provider_selectors)}
    fixtures.sort(key=lambda item: min(
        ordered.get(item.id, 10_000),
        ordered.get(item.code, 10_000),
    ))
    missing = [
        selector for selector in provider_selectors
        if not any(selector in {item.id, item.code} for item in fixtures)
    ]
    if missing:
        raise RuntimeError(f"Provider not found: {', '.join(missing)}")
    return fixtures


async def load_template(
    session: AsyncSession,
    output_dir: Path,
    asset_id: str | None,
) -> Image.Image:
    statement = select(Asset).where(
        Asset.deleted_at.is_(None),
        Asset.category == "model_template",
    )
    if asset_id:
        statement = statement.where(Asset.id == asset_id)
    else:
        statement = statement.order_by(
            case(
                ((Asset.width * 4 == Asset.height * 3), 0),
                else_=1,
            ),
            Asset.created_at.desc(),
        ).limit(1)
    asset = await session.scalar(statement)
    if asset is None:
        raise RuntimeError("No usable model_template asset was found")
    content = await read_asset_content(asset, get_storage_service())
    try:
        source = Image.open(BytesIO(content)).convert("RGB")
    except UnidentifiedImageError as error:
        raise RuntimeError(f"Template asset {asset.id} is not a readable image") from error
    source = center_crop_ratio(source, 3 / 4)
    source.save(output_dir / "template-3x4.jpg", quality=95)
    dump_json(output_dir / "template.json", {
        "asset_id": asset.id,
        "filename": asset.filename,
        "original_width": asset.width,
        "original_height": asset.height,
        "test_width": source.width,
        "test_height": source.height,
    })
    return source


def center_crop_ratio(image: Image.Image, target_ratio: float) -> Image.Image:
    ratio = image.width / image.height
    if abs(ratio - target_ratio) < 0.002:
        return image.copy()
    if ratio > target_ratio:
        width = round(image.height * target_ratio)
        left = (image.width - width) // 2
        return image.crop((left, 0, left + width, image.height))
    height = round(image.width / target_ratio)
    top = (image.height - height) // 2
    return image.crop((0, top, image.width, top + height))


def build_grid(template: Image.Image, size: str, destination: Path) -> Path:
    width, height = parse_size(size)
    if not width or not height:
        width, height = 2048, 2736
    gap_x = max(8, round(width * 48 / 2496))
    gap_y = max(8, round(height * 48 / 3312))
    panel_width = (width - gap_x) // 2
    panel_height = (height - gap_y) // 2
    canvas = Image.new("RGB", (width, height), (245, 0, 245))
    fitted = center_crop_ratio(template, panel_width / panel_height).resize(
        (panel_width, panel_height),
        Image.Resampling.LANCZOS,
    )
    boxes = (
        (0, 0),
        (panel_width + gap_x, 0),
        (0, panel_height + gap_y),
        (panel_width + gap_x, panel_height + gap_y),
    )
    for x, y in boxes:
        canvas.paste(fitted, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((panel_width, 0, panel_width + gap_x - 1, height - 1), fill=(245, 0, 245))
    draw.rectangle((0, panel_height, width - 1, panel_height + gap_y - 1), fill=(245, 0, 245))
    canvas.save(destination, quality=96)
    return destination


def adapter_preview(
    fixture: ProviderFixture,
    endpoint: str,
    size: str,
    ratio: str,
) -> tuple[str | None, str | None, dict[str, object] | None, str | None]:
    raw_payload: dict[str, object] = {
        "prompt": GENERATION_PROMPT if endpoint == "generations" else EDIT_PROMPT,
        "size": size,
        "aspect_ratio": ratio,
        "quality": "high",
        "n": 1,
    }
    try:
        # Mirror the production chain: JobInput normalization first resolves
        # delivery dimensions, then task submission maps them to the model's
        # verified provider working ratio/size before the adapter builds the
        # final New API body.
        payload = normalize_image_job_input(raw_payload)
        validate_submission_dimensions(
            payload,
            fixture.config,
            capability="image_generation" if endpoint == "generations" else "image_edit",
        )
        fields, field, value = provider_dimension_fields(
            payload,
            fixture.config,
            is_edit=endpoint == "edits",
        )
        body: dict[str, object] = {
            "model": fixture.upstream_model,
            "prompt": payload["prompt"],
            "n": 1,
            "response_format": "b64_json",
            **fields,
            "quality": "high",
        }
        if endpoint == "edits" and isinstance(fixture.config.get("edit_body_fields"), list):
            allowed = {str(item) for item in fixture.config["edit_body_fields"]}
            body = {key: value for key, value in body.items() if key in allowed}
        return field, value, body, None
    except (ImageSizeError, ValueError) as error:
        return None, None, None, str(error)


async def download_response_image(
    client: httpx.AsyncClient,
    item: dict[str, object],
) -> tuple[bytes, str]:
    if item.get("b64_json"):
        return base64.b64decode(str(item["b64_json"]), validate=True), "image/png"
    url = str(item.get("url") or "")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("response did not contain a valid image URL")
    response = await client.get(url, follow_redirects=False)
    response.raise_for_status()
    return response.content, response.headers.get("content-type", "image/png").split(";", 1)[0]


def classify_http(status_code: int, message: str) -> tuple[str, str]:
    lowered = message.lower()
    if status_code == 524 or "timeout" in lowered or "timed out" in lowered:
        return "TIMEOUT", "http_timeout"
    if status_code in {400, 422}:
        if any(token in lowered for token in ("upstream", "codex", "chatgpt")):
            return "REJECTED_UPSTREAM", "upstream_rejected"
        return "REJECTED_NEWAPI", "newapi_rejected"
    if status_code >= 500:
        return "REJECTED_UPSTREAM", "upstream_5xx"
    return "UNSUPPORTED", "http_error"


def crop_grid(
    image_path: Path,
    requested_size: str,
    test_dir: Path,
) -> tuple[str | None, list[str], str | None, bool | None]:
    req_width, req_height = parse_size(requested_size)
    if not req_width or not req_height:
        return None, [], None, None
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        exact_plan = requested_size == "2496x3312"
        if exact_plan:
            planned = (
                (0, 0, 1224, 1632),
                (1272, 0, 2496, 1632),
                (0, 1680, 1224, 3312),
                (1272, 1680, 2496, 3312),
            )
        else:
            gap_x = max(8, round(req_width * 48 / 2496))
            gap_y = max(8, round(req_height * 48 / 3312))
            panel_width = (req_width - gap_x) // 2
            panel_height = (req_height - gap_y) // 2
            planned = (
                (0, 0, panel_width, panel_height),
                (panel_width + gap_x, 0, req_width, panel_height),
                (0, panel_height + gap_y, panel_width, req_height),
                (panel_width + gap_x, panel_height + gap_y, req_width, req_height),
            )
        scale_x, scale_y = image.width / req_width, image.height / req_height
        mode = "exact_coordinates" if scale_x == 1 and scale_y == 1 else "proportional_coordinates"
        crop_dir = test_dir / "crops"
        crop_dir.mkdir(exist_ok=True)
        files: list[str] = []
        dimensions: set[tuple[int, int]] = set()
        valid = True
        for index, box in enumerate(planned, start=1):
            scaled = (
                round(box[0] * scale_x),
                round(box[1] * scale_y),
                round(box[2] * scale_x),
                round(box[3] * scale_y),
            )
            crop = image.crop(scaled)
            stats = ImageStat.Stat(crop)
            valid = valid and crop.width > 0 and crop.height > 0 and sum(stats.var) > 1
            path = crop_dir / f"panel-{index}.png"
            crop.save(path)
            files.append(str(path))
            dimensions.add(crop.size)
        crop_size = (
            f"{next(iter(dimensions))[0]}x{next(iter(dimensions))[1]}"
            if len(dimensions) == 1 else "mixed"
        )
        return mode, files, crop_size, bool(valid and len(dimensions) == 1)


async def run_one(
    fixture: ProviderFixture,
    endpoint: str,
    size: str,
    repeat: int,
    template: Image.Image,
    run_dir: Path,
    connect_timeout: float,
    read_timeout: float,
) -> TestResult:
    test_id = f"{fixture.code}-{endpoint}-{size}-{repeat}-{uuid4().hex[:8]}"
    test_dir = run_dir / fixture.code / endpoint / f"{size}-run-{repeat}"
    test_dir.mkdir(parents=True, exist_ok=True)
    ratio = aspect_ratio(size)
    requested_width, requested_height = parse_size(size)
    endpoint_config = "images_endpoint" if endpoint == "generations" else "edits_endpoint"
    default_endpoint = "/images/generations" if endpoint == "generations" else "/images/edits"
    url = provider_url(fixture.base_url, str(fixture.config.get(endpoint_config) or default_endpoint))
    field, value, preview, preflight_error = adapter_preview(fixture, endpoint, size, ratio)
    request_record = {
        "test_id": test_id,
        "provider_id": fixture.id,
        "provider_code": fixture.code,
        "provider_name": fixture.name,
        "provider_type": fixture.provider_type,
        "base_url": fixture.base_url,
        "endpoint_url": url,
        "model": fixture.upstream_model,
        "size": size,
        "aspect_ratio": ratio,
        "quality": "high",
        "n": 1,
        "response_format": "b64_json",
        "key_id": fixture.key_id,
        "key_label": fixture.key_label,
        "key_status_at_start": fixture.key_status,
        "authorization": "<redacted>",
        "adapter_preview": preview,
        "adapter_preflight_error": preflight_error,
    }
    request_file = test_dir / "request.json"
    dump_json(request_file, request_record)
    grid_path = None
    if endpoint == "edits":
        grid_path = build_grid(template, size, test_dir / "input-grid.jpg")
    response_file: Path | None = None
    result_file: Path | None = None
    http_status = None
    response_content_type = None
    response_headers: dict[str, str] = {}
    error_type = error_code = error_message = None
    actual_width = actual_height = None
    size_match = None
    result_level = "UNSUPPORTED"
    crop_mode = crop_size = None
    crop_files: list[str] = []
    crop_valid = None
    started_at = datetime.now(UTC)
    started = monotonic()
    finished_at = started_at
    timeout = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=min(120.0, read_timeout),
        pool=connect_timeout,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            headers = {"Authorization": f"Bearer {fixture.api_key}"}
            if endpoint == "generations":
                body = {
                    "model": fixture.upstream_model,
                    "prompt": GENERATION_PROMPT,
                    "size": size,
                    "aspect_ratio": ratio,
                    "quality": "high",
                    "n": 1,
                    "response_format": "b64_json",
                }
                response = await client.post(url, headers=headers, json=body)
            else:
                data = {
                    "model": fixture.upstream_model,
                    "prompt": EDIT_PROMPT,
                    "size": size,
                    "aspect_ratio": ratio,
                    "quality": "high",
                    "n": "1",
                    "response_format": "b64_json",
                }
                response = await client.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"image": ("input-grid.jpg", grid_path.read_bytes(), "image/jpeg")},
                )
            finished_at = datetime.now(UTC)
            http_status = response.status_code
            response_content_type = response.headers.get("content-type")
            response_headers = {
                name: response.headers[name]
                for name in SAFE_RESPONSE_HEADERS if name in response.headers
            }
            dump_json(test_dir / "response-headers.json", response_headers)
            suffix = ".json" if "json" in (response_content_type or "").lower() else ".bin"
            response_file = test_dir / f"response-body{suffix}"
            response_file.write_bytes(response.content)
            if response.status_code >= 400:
                try:
                    error_body = response.json()
                    upstream_error = error_body.get("error", error_body)
                    message = upstream_error.get("message") if isinstance(upstream_error, dict) else upstream_error
                except ValueError:
                    message = response.text[:1000]
                error_message = safe_error(message, [fixture.api_key])
                result_level, error_code = classify_http(response.status_code, error_message)
                error_type = "http"
            else:
                body = response.json()
                items = body.get("data")
                if not isinstance(items, list) or not items:
                    raise ValueError("successful response contains no data images")
                content, mime_type = await download_response_image(client, items[0])
                extension = "png" if "png" in mime_type else "jpg"
                result_file = test_dir / f"result.{extension}"
                result_file.write_bytes(content)
                with Image.open(result_file) as image:
                    actual_width, actual_height = image.size
                size_match = (
                    requested_width is not None
                    and requested_height is not None
                    and actual_width == requested_width
                    and actual_height == requested_height
                )
                result_level = "SUPPORTED_EXACT" if size_match else "SUPPORTED_SCALED"
                crop_mode, crop_files, crop_size, crop_valid = crop_grid(
                    result_file,
                    size,
                    test_dir,
                )
    except httpx.TimeoutException as error:
        finished_at = datetime.now(UTC)
        error_type = "timeout"
        error_code = "client_timeout"
        error_message = safe_error(error, [fixture.api_key])
        result_level = "TIMEOUT"
    except (httpx.HTTPError, ValueError, KeyError, UnidentifiedImageError) as error:
        finished_at = datetime.now(UTC)
        error_type = "response_or_network"
        error_code = error.__class__.__name__
        error_message = safe_error(error, [fixture.api_key])
        result_level = "UNSUPPORTED"
    return TestResult(
        test_id=test_id,
        provider_id=fixture.id,
        provider_code=fixture.code,
        provider_name=fixture.name,
        endpoint=endpoint,
        endpoint_url=url,
        model=fixture.upstream_model,
        request_size=size,
        request_aspect_ratio=ratio,
        repeat=repeat,
        request_started_at=started_at.isoformat(),
        response_finished_at=finished_at.isoformat(),
        duration_ms=round((monotonic() - started) * 1000),
        http_status=http_status,
        response_content_type=response_content_type,
        server=response_headers.get("server"),
        cf_ray=response_headers.get("cf-ray"),
        upstream_request_id=response_headers.get("x-request-id"),
        retry_after=response_headers.get("retry-after"),
        error_type=error_type,
        error_code=error_code,
        error_message=error_message,
        requested_width=requested_width,
        requested_height=requested_height,
        actual_width=actual_width,
        actual_height=actual_height,
        size_match=size_match,
        result_level=result_level,
        result_file=str(result_file) if result_file else None,
        request_file=str(request_file),
        response_file=str(response_file) if response_file else None,
        adapter_dimension_field=field,
        adapter_dimension_value=value,
        adapter_request_body=preview,
        adapter_preflight_error=preflight_error,
        crop_mode=crop_mode,
        crop_files=crop_files,
        crop_size=crop_size,
        crop_valid=crop_valid,
    )


def report_markdown(
    fixtures: list[ProviderFixture],
    results: list[TestResult],
    run_dir: Path,
    args: argparse.Namespace,
) -> str:
    lines = [
        "# New API GPT 图片自定义尺寸能力测试",
        "",
        f"- 测试时间：{datetime.now(UTC).isoformat()}",
        f"- 模型：`{args.model_code}`",
        f"- 样本：每个节点/接口/尺寸 {args.repeat} 次",
        f"- 超时：connect={args.connect_timeout}s，read={args.read_timeout}s",
        "- 测试方式：直接上游诊断，不创建正式 Job、额度预占或 Celery 消息。",
        "",
        "## 节点",
        "",
    ]
    for fixture in fixtures:
        lines.append(
            f"- `{fixture.code}`：{fixture.base_url}；key={fixture.key_label}"
            f"（状态 {fixture.key_status}，密钥未写入报告）"
        )
    lines += [
        "",
        "## 结果",
        "",
        "| New API | 接口 | 请求尺寸 | HTTP | 实际尺寸 | 耗时 | Provider预览 | 结果 |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for result in results:
        actual = (
            f"{result.actual_width}×{result.actual_height}"
            if result.actual_width and result.actual_height else "—"
        )
        preview = (
            f"{result.adapter_dimension_field}={result.adapter_dimension_value}"
            if result.adapter_dimension_field else f"拒绝：{result.adapter_preflight_error}"
        )
        lines.append(
            f"| {result.provider_code} | {result.endpoint} | {result.request_size.replace('x', '×')} "
            f"| {result.http_status or '—'} | {actual} | {result.duration_ms / 1000:.1f}s "
            f"| {preview} | {result.result_level} |"
        )
    lines += ["", "## 2496×3312", ""]
    largest = [item for item in results if item.request_size == "2496x3312"]
    for item in largest:
        lines.append(
            f"- {item.provider_code}/{item.endpoint}：{item.result_level}；"
            f"实际 {item.actual_width or '—'}×{item.actual_height or '—'}；"
            f"裁切 {item.crop_mode or '—'}，单格 {item.crop_size or '—'}，有效={item.crop_valid}。"
        )
    lines += [
        "",
        "## 注意",
        "",
        "- `SUPPORTED_EXACT` 仅代表本次样本尺寸完全一致，不代表多次调用稳定性。",
        "- `proportional_coordinates` 表示上游缩放后按比例裁切，不是原尺寸精确裁切。",
        "- 布局、人物完整性和放大质量仍需结合保存的结果图与四张 crop 进行视觉复核。",
        f"- 完整结构化结果：`{run_dir / 'report.json'}`",
    ]
    return "\n".join(lines) + "\n"


def refresh_report(
    run_dir: Path,
    fixtures: list[ProviderFixture],
    args: argparse.Namespace,
) -> None:
    report_path = run_dir / "report.json"
    raw_results = json.loads(report_path.read_text(encoding="utf-8"))
    fixture_by_code = {item.code: item for item in fixtures}
    results: list[TestResult] = []
    for raw_result in raw_results:
        result = TestResult(**raw_result)
        fixture = fixture_by_code[result.provider_code]
        field, value, preview, preflight_error = adapter_preview(
            fixture,
            result.endpoint,
            result.request_size,
            result.request_aspect_ratio,
        )
        result.adapter_dimension_field = field
        result.adapter_dimension_value = value
        result.adapter_request_body = preview
        result.adapter_preflight_error = preflight_error
        request_path = Path(result.request_file)
        if request_path.exists():
            request_record = json.loads(request_path.read_text(encoding="utf-8"))
            request_record["adapter_preview"] = preview
            request_record["adapter_preflight_error"] = preflight_error
            dump_json(request_path, request_record)
        results.append(result)
    dump_json(report_path, [asdict(item) for item in results])
    (run_dir / "report.md").write_text(
        report_markdown(fixtures, results, run_dir, args),
        encoding="utf-8",
    )


async def main() -> int:
    args = parse_args()
    if args.refresh_report_dir:
        run_dir = Path(args.refresh_report_dir).resolve()
        raw_results = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        provider_codes = list(dict.fromkeys(str(item["provider_code"]) for item in raw_results))
        session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
        async with session_factory() as session:
            fixtures = await load_fixtures(
                session,
                args.providers or provider_codes,
                args.model_code,
            )
        args.repeat = max(int(item["repeat"]) for item in raw_results)
        refresh_report(run_dir, fixtures, args)
        print(f"REPORT_DIR={run_dir}", flush=True)
        return 0
    if not args.providers:
        raise SystemExit("Pass both nodes with --provider PROVIDER_ID_OR_CODE")
    if args.repeat < 1 or args.repeat > 2:
        raise SystemExit("--repeat must be 1 or 2")
    endpoints = args.endpoint or ["generations", "edits"]
    sizes = list(args.sizes or DEFAULT_SIZES)
    if args.include_fixed_sizes:
        sizes.extend(size for size in FIXED_SIZES if size not in sizes)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.output_root).resolve() / timestamp
    run_dir.mkdir(parents=True)
    session_factory = async_sessionmaker(
        get_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        fixtures = await load_fixtures(session, args.providers, args.model_code)
        template = await load_template(
            session,
            run_dir,
            args.template_asset_id,
        )
    dump_json(run_dir / "providers.json", [{
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "base_url": item.base_url,
        "provider_type": item.provider_type,
        "model_id": item.model_id,
        "model_code": item.model_code,
        "upstream_model": item.upstream_model,
        "key_id": item.key_id,
        "key_label": item.key_label,
        "key_status": item.key_status,
        "config": item.config,
        "api_key": "<redacted>",
    } for item in fixtures])
    results: list[TestResult] = []
    for fixture in fixtures:
        for endpoint in endpoints:
            for size in sizes:
                for repeat in range(1, args.repeat + 1):
                    result = await run_one(
                        fixture,
                        endpoint,
                        size,
                        repeat,
                        template,
                        run_dir,
                        args.connect_timeout,
                        args.read_timeout,
                    )
                    results.append(result)
                    dump_json(run_dir / "report.json", [asdict(item) for item in results])
                    print(
                        f"{result.provider_code} {endpoint} {size}: "
                        f"{result.result_level} HTTP={result.http_status} "
                        f"actual={result.actual_width}x{result.actual_height} "
                        f"duration={result.duration_ms}ms",
                        flush=True,
                    )
    (run_dir / "report.md").write_text(
        report_markdown(fixtures, results, run_dir, args),
        encoding="utf-8",
    )
    print(f"REPORT_DIR={run_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

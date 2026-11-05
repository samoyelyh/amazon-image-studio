"""Opt-in online Responses image adapter, with one HTTP request per execution.

The controller may perform multiple hosted image-tool calls in that response.
This is not a local CLI bridge, an Images API fallback, or a collage splitter.
"""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import re

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.providers.base import BaseImageProvider, ProviderError, ProviderOutput, ProviderResult
from app.providers.openai_compatible import _error_message, _provider_timeout, _retry_after_seconds
from app.providers.urls import provider_url
from app.services.batch_tryon_native_multi_service import validate_native_multi_output


def build_responses_image_request(*, upstream_model: str, capability: str,
                                  payload: dict[str, object], config: dict[str, object]) -> dict:
    if capability not in {"image_generation", "image_edit", "multi_image_reference"} or payload.get("mask_image"):
        raise ProviderError("provider.unsupported_capability", "当前Responses通道未验证严格蒙版编辑能力。", http_status=422)
    count = payload.get("n", 1)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise ProviderError("provider.invalid_output_count", "独立图片数量必须是1到10之间的整数。", http_status=422)
    if count > 1 and config.get("responses_multi_output_enabled") is not True:
        raise ProviderError("provider.multi_output_not_verified", "当前线上Responses通道尚未验证多图返回能力。", http_status=422)
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ProviderError("provider.missing_prompt", "生图提示词不能为空。", http_status=422)
    references = payload.get("reference_images") or []
    if not isinstance(references, list):
        raise ProviderError("provider.invalid_reference", "图片参考输入格式无效。", http_status=422)
    if capability != "image_generation" and not references:
        raise ProviderError("provider.missing_reference", "图片编辑需要真实参考图片。", http_status=422)
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    for reference in references:
        if not isinstance(reference, dict) or not isinstance(reference.get("content"), bytes) or not reference["content"]:
            raise ProviderError("provider.invalid_reference", "参考图片内容无效。", http_status=422)
        mime = str(reference.get("mime_type") or "image/png")
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            raise ProviderError("provider.invalid_reference", "参考图片仅支持PNG、JPEG、WEBP。", http_status=422)
        content.append({"type": "input_image", "image_url":
            f"data:{mime};base64,{base64.b64encode(reference['content']).decode('ascii')}"})
    output_format = str(payload.get("output_format") or "png")
    quality = str(payload.get("quality") or "high")
    if output_format not in {"png", "jpeg", "webp"} or quality not in {"auto", "low", "medium", "high"}:
        raise ProviderError("provider.invalid_image_options", "图片质量或格式无效。", http_status=422)
    tool = {"type": "image_generation", "action": "generate" if capability == "image_generation" else "edit",
        "size": str(payload.get("provider_size") or payload.get("size") or "auto"),
        "quality": quality, "output_format": output_format}
    image_model = config.get("image_generation_model")
    if image_model:
        tool["model"] = str(image_model)
    request = {"model": upstream_model, "input": [{"role": "user", "content": content}],
        "tools": [tool], "tool_choice": {"type": "image_generation"},
        "max_tool_calls": count, "parallel_tool_calls": True, "stream": False, "store": False,
        "instructions": (
            f"Return exactly {count} separate, independently encoded image_generation_call results. "
            "Do not replace separate images with a collage or a contact sheet. "
            "For distinct input products, follow the product-pair manifest in the user prompt; "
            "do not produce repeated variations of one product. Preserve all user-specified product and template constraints."
        )}
    if config.get("responses_supports_max_tool_calls") is False:
        # Some relay Responses implementations reject this optional parameter.
        # Do not claim a hard server-side call cap when it cannot be submitted.
        request.pop("max_tool_calls")
        request["instructions"] += (
            f" Do not execute more than {count} image tool calls. "
            "Do not generate extra alternatives or automatically retry failed image calls."
        )
    # Never transmit an operator-provided identifier verbatim.
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("safety_identifier"):
        request["safety_identifier"] = sha256(str(metadata["safety_identifier"]).encode()).hexdigest()
    return request


def parse_responses_images(body: object, *, expected_count: int, max_bytes: int,
                           requested_model: str, request_id: str | None = None) -> ProviderResult:
    if not isinstance(body, dict) or not isinstance(body.get("output"), list):
        raise ProviderError("provider.invalid_response", "上游没有返回有效的Responses输出列表。")
    if body.get("status") != "completed":
        raise ProviderError("provider.response_incomplete", "线上Responses未完成，不能将部分输出视为整组成功。")
    actual_model = str(body.get("model") or "")
    if actual_model and actual_model != requested_model and not actual_model.startswith(requested_model + "-"):
        raise ProviderError("provider.model_mismatch", "上游返回的控制模型与指定模型不一致，未接受替换型号。")
    calls = [item for item in body["output"] if isinstance(item, dict) and item.get("type") == "image_generation_call"]
    outputs, call_ids = [], []
    for index, call in enumerate(calls, 1):
        encoded = call.get("result")
        if call.get("status") not in {None, "completed"} or not isinstance(encoded, str) or not encoded:
            raise ProviderError("provider.image_call_incomplete", "上游存在未完成或没有图片的生图工具调用。")
        if len(encoded) > ((max_bytes + 2) // 3) * 4:
            raise ProviderError("provider.output_too_large", "上游返回图片超过大小上限。")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as error:
            raise ProviderError("provider.invalid_image", "上游图片编码无效。") from error
        if len(data) > max_bytes:
            raise ProviderError("provider.output_too_large", "上游返回图片超过大小上限。")
        try:
            with Image.open(BytesIO(data)) as image:
                image.verify()
                format = image.format
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise ProviderError("provider.invalid_image", "上游工具返回的内容不是有效图片。") from error
        mime, extension = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"),
            "WEBP": ("image/webp", "webp")}.get(format, (None, None))
        if mime is None:
            raise ProviderError("provider.invalid_image", "上游图片格式不受支持。")
        outputs.append(ProviderOutput(data, mime, f"response-{index}.{extension}"))
        call_ids.append(call.get("id"))
    result = ProviderResult(outputs, request_id or body.get("id"), {
        "protocol": "responses", "controller_model": requested_model,
        "actual_controller_model": actual_model or None,
        "requested_output_count": expected_count, "actual_output_count": len(outputs),
        "image_generation_call_count": len(calls), "output_call_ids": call_ids,
        "upstream_http_request_count": 1, "output_transform": "none",
        "mapping_status": "needs_visual_review" if expected_count > 1 else "single_output",
    })
    validate_native_multi_output(result, expected_count)
    return result


class OpenAIResponsesImageProvider(BaseImageProvider):
    def __init__(self, settings: Settings):
        self.settings = settings

    async def execute(self, *, base_url: str, api_key: str, upstream_model: str,
                      capability: str, payload: dict[str, object], config: dict[str, object]) -> ProviderResult:
        body = build_responses_image_request(upstream_model=upstream_model, capability=capability, payload=payload, config=config)
        try:
            async with httpx.AsyncClient(timeout=_provider_timeout(self.settings), follow_redirects=False) as client:
                response = await client.post(provider_url(base_url, str(config.get("responses_endpoint") or "/responses")),
                    headers={"Authorization": f"Bearer {api_key}"}, json=body)
        except httpx.TimeoutException as error:
            raise ProviderError("provider.timeout", "线上Responses请求超时；远端结果未知，不应自动改用其他通道重复生成。", retryable=False) from error
        except httpx.HTTPError as error:
            raise ProviderError("provider.network_error", f"线上Responses连接中断（{type(error).__name__}）；远端结果未知，未自动补发。", retryable=False) from error
        if response.status_code >= 400:
            try:
                message = _error_message(response)
            except (AttributeError, TypeError):
                message = f"Upstream provider returned HTTP {response.status_code}"
            message = message.replace(api_key, "[REDACTED]")
            message = re.sub(r"(?i)Bearer\s+\S+|sk-[A-Za-z0-9_-]{10,}", "[REDACTED]", message)
            try:
                error_body = response.json().get("error", {})
            except (ValueError, AttributeError):
                error_body = {}
            missing_model = isinstance(error_body, dict) and error_body.get("code") in {"model_not_found", "model_not_available"}
            code = "provider.model_unavailable" if missing_model else "provider.rate_limited" if response.status_code == 429 else "provider.upstream_error"
            if missing_model:
                message = f"线上中转未为当前令牌开通指定模型 {upstream_model}；未切换其他型号。" + message
            raise ProviderError(code, message, http_status=response.status_code,
                retryable=response.status_code == 429 and not missing_model,
                retry_after_seconds=_retry_after_seconds(response))
        try:
            result_body = response.json()
        except ValueError as error:
            raise ProviderError("provider.invalid_response", "上游没有返回有效的非流式Responses JSON。") from error
        result = parse_responses_images(result_body, expected_count=payload.get("n", 1),
            max_bytes=self.settings.provider_output_max_bytes, requested_model=upstream_model,
            request_id=response.headers.get("x-request-id"))
        result.metadata["submitted_tool_call_limit"] = body.get("max_tool_calls")
        return result

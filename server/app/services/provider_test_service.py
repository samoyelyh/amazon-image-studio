from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.providers.base import ProviderError
from app.providers.registry import get_provider_adapter
from app.providers.urls import provider_url


@dataclass(frozen=True)
class ProviderConnectionResult:
    success: bool
    status_code: int | None
    error_code: str | None
    message: str
    models: list[str]


async def probe_provider_models(
    *, base_url: str, api_key: str, timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProviderConnectionResult:
    """Test an OpenAI-compatible model endpoint without logging credentials or response bodies."""
    if not api_key.strip():
        return ProviderConnectionResult(False, None, "provider.missing_api_key", "API Key 为空", [])
    url = provider_url(base_url, "/models")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds), follow_redirects=False, transport=transport,
        ) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.TimeoutException:
        return ProviderConnectionResult(False, None, "provider.timeout", "中转站请求超时", [])
    except httpx.HTTPError:
        return ProviderConnectionResult(False, None, "provider.network_error", "无法连接中转站", [])

    if response.status_code != 200:
        code, message = _status_error(response.status_code)
        return ProviderConnectionResult(False, response.status_code, code, message, [])
    try:
        payload = response.json()
        data = payload["data"]
        if not isinstance(data, list):
            raise TypeError
        models = sorted({
            str(item["id"]).strip() for item in data
            if isinstance(item, dict) and item.get("id") and str(item["id"]).strip()
        })
    except (ValueError, KeyError, TypeError):
        return ProviderConnectionResult(False, 200, "provider.invalid_response", "模型列表响应格式不兼容", [])
    if not models:
        return ProviderConnectionResult(False, 200, "provider.empty_models", "中转站未返回任何模型", [])
    return ProviderConnectionResult(True, 200, None, f"连接成功，发现 {len(models)} 个模型", models[:500])


async def probe_provider_operation(
    *, settings: Settings, provider_type: str, base_url: str, api_key: str,
    upstream_model: str, capability: str, provider_config: dict[str, object],
    model_config: dict[str, object], reference_images: list[dict[str, object]] | None = None,
) -> ProviderConnectionResult:
    adapter = get_provider_adapter(provider_type, settings)
    if capability == "text_generation":
        payload: dict[str, object] = {
            "system_prompt": "Return one JSON object only.",
            "user_prompt": 'Return exactly {"ok":true}.',
            "temperature": 0,
        }
    elif capability == "image_generation":
        payload = {"prompt": "A small blue square on a white background.", "n": 1, "size": "1024x1024"}
    else:
        if not reference_images:
            return ProviderConnectionResult(False, None, "provider.missing_reference", "图片编辑测试缺少参考图", [])
        payload = {
            "prompt": "Keep the image composition unchanged and make the blue color slightly lighter.",
            "n": 1, "size": "1024x1024", "reference_images": reference_images,
        }
    try:
        result = await adapter.execute(
            base_url=base_url, api_key=api_key, upstream_model=upstream_model,
            capability=capability, payload=payload, config={**provider_config, **model_config},
        )
    except ProviderError as error:
        return ProviderConnectionResult(False, error.http_status, error.code, error.message, [])
    label = {
        "text_generation": "文本模型",
        "image_generation": "图片生成",
        "image_edit": "图片编辑",
        "multi_image_reference": "多参考图编辑",
    }.get(capability, capability)
    detail = "返回文本有效" if capability == "text_generation" else f"返回 {len(result.outputs)} 张图片"
    return ProviderConnectionResult(True, 200, None, f"{label}测试成功，{detail}", [])


def _status_error(status_code: int) -> tuple[str, str]:
    mapping = {
        401: ("provider.invalid_api_key", "API Key 无效或鉴权格式不正确"),
        403: ("provider.model_forbidden", "API Key 没有访问权限"),
        404: ("provider.endpoint_not_found", "Base URL 或模型列表路径不存在"),
        408: ("provider.timeout", "中转站请求超时"),
        429: ("provider.rate_limited", "中转站限流或额度不足"),
        522: ("provider.origin_timeout", "中转站源站连接超时（Cloudflare 522）"),
    }
    if status_code in mapping:
        return mapping[status_code]
    if status_code in {500, 502, 503, 504} or status_code >= 520:
        return "provider.unavailable", f"中转站暂时不可用（HTTP {status_code}）"
    return "provider.upstream_error", f"中转站返回 HTTP {status_code}"

from __future__ import annotations

import base64
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.providers.base import BaseImageProvider, ProviderError, ProviderOutput, ProviderResult
from app.providers.urls import provider_url
from app.services.image_size_service import ImageSizeError, provider_dimension_fields


class OpenAICompatibleProvider(BaseImageProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(
        self, *, base_url: str, api_key: str, upstream_model: str,
        capability: str, payload: dict[str, object], config: dict[str, object],
    ) -> ProviderResult:
        if capability == "text_generation":
            return await self._execute_text(
                base_url=base_url, api_key=api_key, upstream_model=upstream_model,
                payload=payload, config=config,
            )
        supported = {"image_generation", "image_edit", "multi_image_reference", "mask_edit"}
        if capability not in supported:
            raise ProviderError("provider.unsupported_capability", "This adapter does not support the requested capability", http_status=422)
        is_edit = capability != "image_generation"
        try:
            dimension_fields, dimension_field, dimension_value = provider_dimension_fields(payload, config, is_edit=is_edit)
        except ImageSizeError as error:
            raise ProviderError(error.code, error.message, http_status=error.http_status) from error
        request_body: dict[str, object] = {
            "model": upstream_model,
            "prompt": payload.get("prompt"),
            "n": payload.get("n", 1),
            "response_format": payload.get("response_format", "b64_json"),
        }
        request_body.update(dimension_fields)
        request_body.update({key: value for key, value in payload.items() if key not in request_body and key in {"quality", "style", "background"}})
        if is_edit:
            configured_fields = config.get("edit_body_fields")
            if isinstance(configured_fields, list):
                allowed_fields = {str(field) for field in configured_fields}
                if dimension_field not in allowed_fields:
                    raise ProviderError(
                        "provider.unsupported_size",
                        f"当前图片编辑模型配置未启用 {dimension_field} 字段，无法保证所选尺寸。",
                        http_status=422,
                    )
                request_body = {key: value for key, value in request_body.items() if key in allowed_fields}
        endpoint = str(config.get("edits_endpoint" if is_edit else "images_endpoint", "/images/edits" if is_edit else "/images/generations"))
        url = provider_url(base_url, endpoint)
        timeout = httpx.Timeout(self.settings.provider_request_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                if is_edit:
                    references = payload.get("reference_images")
                    if not isinstance(references, list) or not references:
                        raise ProviderError("provider.missing_reference", "Image editing requires at least one reference image", http_status=422)
                    files: list[tuple[str, tuple[str, bytes, str]]] = []
                    for index, image in enumerate(references):
                        if not isinstance(image, dict) or not isinstance(image.get("content"), bytes):
                            raise ProviderError("provider.invalid_reference", "Reference image payload is invalid", http_status=422)
                        files.append(("image", (
                            str(image.get("filename") or f"reference-{index + 1}.png"),
                            image["content"], str(image.get("mime_type") or "image/png"),
                        )))
                    mask = payload.get("mask_image")
                    if isinstance(mask, dict) and isinstance(mask.get("content"), bytes):
                        files.append(("mask", (str(mask.get("filename") or "mask.png"), mask["content"], str(mask.get("mime_type") or "image/png"))))
                    form = {key: str(value) for key, value in request_body.items() if value is not None}
                    response = await client.post(url, headers={"Authorization": f"Bearer {api_key}"}, data=form, files=files)
                else:
                    response = await client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=request_body)
        except httpx.TimeoutException as error:
            raise ProviderError("provider.timeout", "Upstream provider timed out", retryable=True) from error
        except httpx.HTTPError as error:
            raise ProviderError("provider.network_error", "Unable to reach upstream provider", retryable=True) from error
        if response.status_code >= 400:
            message = _error_message(response)
            retryable = response.status_code in {408, 409, 429} or response.status_code >= 500
            raise ProviderError("provider.rate_limited" if response.status_code == 429 else "provider.upstream_error", message, http_status=response.status_code, retryable=retryable)
        try:
            body = response.json()
            items = body["data"]
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderError("provider.invalid_response", "Upstream provider returned an invalid image response") from error
        outputs: list[ProviderOutput] = []
        for index, item in enumerate(items):
            if item.get("b64_json"):
                try:
                    content = base64.b64decode(item["b64_json"], validate=True)
                except (ValueError, TypeError) as error:
                    raise ProviderError("provider.invalid_image", "Upstream returned invalid base64 image data") from error
                if len(content) > self.settings.provider_output_max_bytes:
                    raise ProviderError("provider.output_too_large", "Generated image exceeds the configured size limit")
                outputs.append(_output(content, "image/png", index))
            elif item.get("url"):
                outputs.append(await self._download_image(str(item["url"]), index))
        if not outputs:
            raise ProviderError("provider.empty_result", "Upstream provider returned no images")
        return ProviderResult(outputs, response.headers.get("x-request-id"), {
            "created": body.get("created"),
            "submitted_dimension_field": dimension_field,
            "submitted_dimension_value": dimension_value,
        })

    async def _execute_text(
        self, *, base_url: str, api_key: str, upstream_model: str,
        payload: dict[str, object], config: dict[str, object],
    ) -> ProviderResult:
        endpoint = str(config.get("chat_endpoint", "/chat/completions"))
        url = provider_url(base_url, endpoint)
        user_content: object = str(payload.get("user_prompt") or "")
        references = payload.get("reference_images")
        if isinstance(references, list) and references:
            parts: list[dict[str, object]] = [{"type": "text", "text": user_content}]
            for image in references:
                if not isinstance(image, dict) or not isinstance(image.get("content"), bytes):
                    raise ProviderError("provider.invalid_reference", "Reference image payload is invalid", http_status=422)
                mime = str(image.get("mime_type") or "image/png")
                encoded = base64.b64encode(image["content"]).decode("ascii")
                parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
            user_content = parts
        request_body: dict[str, object] = {
            "model": upstream_model,
            "messages": [
                {"role": "system", "content": str(payload.get("system_prompt") or "")},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if payload.get("temperature") is not None:
            request_body["temperature"] = payload["temperature"]
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.settings.provider_request_timeout_seconds), follow_redirects=False) as client:
                response = await client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=request_body)
        except httpx.TimeoutException as error:
            raise ProviderError("provider.timeout", "Upstream provider timed out", retryable=True) from error
        except httpx.HTTPError as error:
            raise ProviderError("provider.network_error", "Unable to reach upstream provider", retryable=True) from error
        if response.status_code >= 400:
            retryable = response.status_code in {408, 409, 429} or response.status_code >= 500
            raise ProviderError(
                "provider.rate_limited" if response.status_code == 429 else "provider.upstream_error",
                _error_message(response), http_status=response.status_code, retryable=retryable,
            )
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
            text = str(content).strip()
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderError("provider.invalid_response", "Upstream provider returned an invalid text response") from error
        if not text:
            raise ProviderError("provider.empty_result", "Upstream provider returned empty text")
        return ProviderResult([], response.headers.get("x-request-id"), {"text": text, "created": body.get("created")})

    async def _download_image(self, url: str, index: int) -> ProviderOutput:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ProviderError("provider.invalid_output_url", "Upstream returned an invalid output URL")
        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_request_timeout_seconds, follow_redirects=False) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise ProviderError("provider.output_download_failed", "Unable to download the generated image", retryable=True) from error
        content = response.content
        if len(content) > self.settings.provider_output_max_bytes:
            raise ProviderError("provider.output_too_large", "Generated image exceeds the configured size limit")
        mime = response.headers.get("content-type", "image/png").split(";", 1)[0].lower()
        if not mime.startswith("image/"):
            raise ProviderError("provider.invalid_output_type", "Generated output is not an image")
        suffix = PurePosixPath(parsed.path).suffix.lstrip(".") or mime.split("/", 1)[1]
        return ProviderOutput(content, mime, f"generated-{index + 1}.{suffix}")


class NewAPIProvider(OpenAICompatibleProvider):
    """NewAPI uses the OpenAI Images wire protocol with a configurable base URL."""


class CustomImageProvider(OpenAICompatibleProvider):
    """Configurable OpenAI-style adapter for private image gateways."""


def _output(content: bytes, mime_type: str, index: int) -> ProviderOutput:
    if not content:
        raise ProviderError("provider.empty_result", "Upstream provider returned an empty image")
    return ProviderOutput(content, mime_type, f"generated-{index + 1}.png")


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error", body)
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
    except ValueError:
        pass
    return f"Upstream provider returned HTTP {response.status_code}"

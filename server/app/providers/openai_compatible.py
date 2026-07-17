from __future__ import annotations

import base64
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.providers.base import BaseImageProvider, ProviderError, ProviderOutput, ProviderResult


class OpenAICompatibleProvider(BaseImageProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(
        self, *, base_url: str, api_key: str, upstream_model: str,
        capability: str, payload: dict[str, object], config: dict[str, object],
    ) -> ProviderResult:
        if capability != "image_generation":
            raise ProviderError("provider.unsupported_capability", "This adapter currently supports image_generation", http_status=422)
        request_body = {
            "model": upstream_model,
            "prompt": payload.get("prompt"),
            "n": payload.get("n", 1),
            "size": payload.get("size", "1024x1024"),
            "response_format": payload.get("response_format", "b64_json"),
        }
        request_body.update({key: value for key, value in payload.items() if key not in request_body and key in {"quality", "style", "background"}})
        endpoint = str(config.get("images_endpoint", "/images/generations"))
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        timeout = httpx.Timeout(self.settings.provider_request_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
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
        return ProviderResult(outputs, response.headers.get("x-request-id"), {"created": body.get("created")})

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

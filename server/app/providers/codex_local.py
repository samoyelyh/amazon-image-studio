from __future__ import annotations

import asyncio
import base64
import math
from asyncio import sleep
from pathlib import PureWindowsPath
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from app.core.config import Settings
from app.providers.base import BaseImageProvider, ProviderError, ProviderOutput, ProviderResult
from app.providers.urls import provider_url


class CodexLocalProvider(BaseImageProvider):
    """Native bridge protocol; api_key is an internal bridge access token."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def execute(
        self, *, base_url: str, api_key: str, upstream_model: str,
        capability: str, payload: dict[str, object], config: dict[str, object],
    ) -> ProviderResult:
        body = self._request_body(upstream_model, capability, payload)
        job_id = body["job_id"]
        try:
            parts = urlsplit(base_url)
            if (parts.scheme not in {"http", "https"} or not parts.hostname
                    or not parts.path.rstrip("/").endswith("/v1")
                    or parts.username or parts.password or parts.query or parts.fragment):
                raise ValueError
            url = provider_url(base_url, "/executions")
        except ValueError:
            raise ProviderError("provider.invalid_base_url", "本机桥接地址必须是以 /v1 结尾的 HTTP(S) 地址", http_status=422) from None
        if len(api_key.strip()) < 32:
            raise ProviderError("provider.invalid_api_key", "桥接访问令牌至少需要 32 个字符（不是 OpenAI Key）", http_status=422)
        interval = self._poll_interval(config)
        cancel_requested = payload.get("_cancel_requested")
        if cancel_requested is not None and not callable(cancel_requested):
            raise ProviderError("provider.invalid_payload", "本机桥接取消回调无效", http_status=422)
        execution_url = f"{url}/{job_id}"
        timeout = httpx.Timeout(
            self.settings.provider_request_timeout_seconds,
            connect=self.settings.provider_connect_timeout_seconds,
        )
        async with httpx.AsyncClient(
            timeout=timeout, trust_env=False, follow_redirects=False,
            headers={"Authorization": f"Bearer {api_key}"},
        ) as client:
            submitted = False

            async def run() -> ProviderResult:
                nonlocal submitted
                # Once submission is attempted, recover only by querying this same ID.
                submitted = True
                response = await self._communicate(client, "POST", url, json=body)
                while True:
                    state = self._state(response, job_id) if response is not None else {}
                    status = state.get("status")
                    if status == "succeeded":
                        try:
                            output = await self._output(client, execution_url)
                        except httpx.HTTPError:
                            pass  # Recover a completed output without submitting another execution.
                        except ProviderError as error:
                            if not error.retryable:
                                raise
                        else:
                            # Never expose untrusted bridge metadata or response bodies.
                            return ProviderResult([output], job_id, {"job_id": job_id, "status": "succeeded"})
                    if status == "cancelled":
                        raise ProviderError("provider.cancelled", "本机 Codex 执行已取消")
                    if status in {"failed", "interrupted"}:
                        error = state.get("error") or {}
                        interrupted = status == "interrupted"
                        safe_message = {
                            "codex.quota": "ChatGPT/Codex额度不足，请等待额度恢复",
                            "codex.auth": "本机Codex登录已失效，请在Windows本机重新登录ChatGPT",
                            "codex.execution_unknown": "本机执行状态未知，未自动重复生成，请核对本机记录",
                            "codex.no_output": "本机Codex没有返回有效图片，未自动重复生成",
                        }.get(error.get("code"))
                        raise ProviderError(
                            "provider.interrupted" if interrupted else "provider.execution_failed",
                            safe_message or ("本机 Codex 执行已中断" if interrupted else "本机 Codex 执行失败"),
                            retryable=error.get("retryable", interrupted),
                        )
                    await sleep(interval)
                    response = await self._communicate(client, "GET", execution_url)

            async def run_with_cancellation() -> ProviderResult:
                await self._check_cancel(cancel_requested)
                if cancel_requested is None:
                    return await run()

                async def watch_cancel() -> None:
                    while True:
                        await sleep(interval)
                        await self._check_cancel(cancel_requested)

                execution = asyncio.create_task(run())
                watcher = asyncio.create_task(watch_cancel())
                try:
                    done, _ = await asyncio.wait({execution, watcher}, return_when=asyncio.FIRST_COMPLETED)
                    if watcher in done:
                        await watcher
                    return await execution
                finally:
                    execution.cancel()
                    watcher.cancel()
                    await asyncio.gather(execution, watcher, return_exceptions=True)

            try:
                return await asyncio.wait_for(run_with_cancellation(), timeout=self.settings.provider_request_timeout_seconds)
            except ProviderError as error:
                if error.code == "provider.cancelled":
                    await self._cancel(client, execution_url)
                raise
            except asyncio.CancelledError:
                await self._cancel(client, execution_url)
                raise
            except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException):
                if submitted:
                    raise ProviderError("provider.execution_unknown", "本机桥接执行结果暂无法确认；请核对原任务，勿切换通道重复生成", retryable=False) from None
                raise ProviderError("provider.timeout", "本机 Codex 桥接请求超时", retryable=True) from None
            except httpx.HTTPError:
                raise ProviderError("provider.execution_unknown", "本机桥接执行结果暂无法确认；请核对原任务，勿切换通道重复生成", retryable=False) from None

    @staticmethod
    async def _communicate(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response | None:
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.HTTPError:
            return None
        if response.is_error:
            # Explicit host admission rejections must not become endless polling.
            try:
                code = response.json().get("error", {}).get("code")
            except (ValueError, AttributeError):
                code = None
            known = {
                "codex.busy": ("provider.rate_limited", "本机执行槽已满，请在平台队列等待", True),
                "codex.auth": ("provider.invalid_api_key", "本机Codex登录或桥接令牌无效", False),
                "codex.skill_missing": ("provider.unavailable", "本机缺少官方imagegen Skill", False),
                "codex.unavailable": ("provider.unavailable", "本机Codex无法启动或登录检查超时", False),
                "codex.idempotency_conflict": ("provider.idempotency_conflict", "相同任务ID的生成输入不一致", False),
                "codex.execution_unknown": ("provider.execution_unknown", "本机存在中断且状态未知的执行，请先核对", False),
            }
            if code in known:
                mapped, message, retryable = known[code]
                raise ProviderError(mapped, message, http_status=response.status_code, retryable=retryable)
        # A lost admission response, transient gateway failure, or absent poll record
        # does not prove that the host never started generation.
        if response.status_code in {408, 409, 429} or response.status_code >= 500:
            return None
        if method == "GET" and response.status_code == 404:
            return None
        return response

    @staticmethod
    def _request_body(model: str, capability: str, payload: dict[str, object]) -> dict[str, object]:
        if capability not in {"image_generation", "image_edit", "multi_image_reference"}:
            raise ProviderError("provider.unsupported_capability", "本机 Codex 桥接不支持此能力", http_status=422)
        if "mask_image" in payload or "mask_asset_id" in payload:
            raise ProviderError("provider.unsupported_capability", "本机 Codex 桥接不支持蒙版编辑", http_status=422)
        job_id = payload.get("job_id")
        try:
            if not isinstance(job_id, str) or str(UUID(job_id)) != job_id:
                raise ValueError
        except ValueError:
            raise ProviderError("provider.invalid_job_id", "本机桥接需要调用方提供规范 UUID 任务 ID", http_status=422) from None
        if type(payload.get("n", 1)) is not int or payload.get("n", 1) != 1:
            raise ProviderError("provider.invalid_payload", "本机 Codex 桥接每个任务仅支持一张图片", http_status=422)
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderError("provider.invalid_payload", "本机桥接需要非空提示词", http_status=422)
        references = payload.get("reference_images", [])
        if not isinstance(references, list):
            raise ProviderError("provider.invalid_reference", "参考图格式无效", http_status=422)
        if len(references) > 5:
            raise ProviderError("provider.too_many_references", "本机 Codex 通道最多支持 5 张有序参考图，请减少参考图后重试", http_status=422)
        if capability != "image_generation" and not references:
            raise ProviderError("provider.missing_reference", "图片编辑需要参考图", http_status=422)
        if capability == "multi_image_reference" and len(references) < 2:
            raise ProviderError("provider.missing_reference", "多参考图编辑至少需要两张参考图", http_status=422)
        encoded = []
        for index, image in enumerate(references):
            if not isinstance(image, dict) or not isinstance(image.get("content"), bytes) or not image["content"]:
                raise ProviderError("provider.invalid_reference", "参考图内容无效", http_status=422)
            mime = image.get("mime_type", "image/png")
            if not isinstance(mime, str) or not mime.startswith("image/") or any(c.isspace() for c in mime):
                raise ProviderError("provider.invalid_reference", "参考图类型无效", http_status=422)
            filename = PureWindowsPath(str(image.get("filename") or f"reference-{index + 1}.png")).name
            encoded.append({
                "filename": filename or f"reference-{index + 1}.png", "mime_type": mime,
                "data_base64": base64.b64encode(image["content"]).decode("ascii"),
            })
        body: dict[str, object] = {
            "job_id": job_id, "model": model, "capability": capability,
            "prompt": prompt, "n": 1, "reference_images": encoded,
        }
        for field in ("size", "quality"):
            value = payload.get(field)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ProviderError("provider.invalid_payload", "本机桥接图片参数无效", http_status=422)
                body[field] = value
        return body

    @staticmethod
    def _poll_interval(config: dict[str, object]) -> float:
        try:
            value = float(config.get("poll_interval_seconds", 1.0))
            if not math.isfinite(value):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ProviderError("provider.invalid_config", "桥接轮询间隔必须是有限数值", http_status=422) from None
        return max(0.1, min(5.0, value))

    @staticmethod
    async def _check_cancel(callback) -> None:
        if callback is not None and await callback():
            raise ProviderError("provider.cancelled", "本机 Codex 执行已取消")

    async def _cancel(self, client: httpx.AsyncClient, execution_url: str) -> None:
        try:
            await asyncio.wait_for(
                client.post(f"{execution_url}/cancel"),
                timeout=min(5.0, self.settings.provider_request_timeout_seconds),
            )
        except (asyncio.TimeoutError, TimeoutError, httpx.HTTPError):
            pass  # Best effort only; never surface a bridge response body or token.

    @staticmethod
    def _check_http(response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        code, message = {
            401: ("provider.invalid_api_key", "本机桥接访问令牌无效"),
            403: ("provider.model_forbidden", "本机桥接访问被拒绝"),
            404: ("provider.endpoint_not_found", "本机桥接接口或任务不存在"),
            429: ("provider.rate_limited", "本机桥接暂时繁忙"),
        }.get(status, ("provider.upstream_error", "本机 Codex 桥接请求失败"))
        raise ProviderError(
            code, message, http_status=status,
            retryable=status in {408, 409, 429} or status >= 500,
        )

    def _state(self, response: httpx.Response, job_id: str) -> dict[str, object]:
        self._check_http(response)
        try:
            state = response.json()
            if (not isinstance(state, dict) or state.get("job_id") != job_id
                    or state.get("status") not in ("running", "succeeded", "failed", "cancelled", "interrupted")):
                raise ValueError
            if "metadata" in state and not isinstance(state["metadata"], dict):
                raise ValueError
            if "error" in state:
                error = state["error"]
                if (not isinstance(error, dict) or not isinstance(error.get("code"), str)
                        or not isinstance(error.get("message"), str) or type(error.get("retryable")) is not bool):
                    raise ValueError
            return state
        except (ValueError, TypeError):
            raise ProviderError("provider.invalid_response", "本机桥接返回的任务状态无效") from None

    async def _output(self, client: httpx.AsyncClient, execution_url: str) -> ProviderOutput:
        async with client.stream("GET", f"{execution_url}/output") as response:
            self._check_http(response)
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime != "image/png":
                raise ProviderError("provider.invalid_output_type", "本机桥接输出必须是 PNG 图片")
            limit = self.settings.provider_output_max_bytes
            length = response.headers.get("content-length")
            if length is not None:
                try:
                    declared_length = int(length)
                    if declared_length < 0:
                        raise ValueError
                except ValueError:
                    raise ProviderError("provider.invalid_response", "本机桥接图片响应长度无效") from None
                if declared_length > limit:
                    raise ProviderError("provider.output_too_large", "本机桥接图片超过大小限制")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > limit:
                    raise ProviderError("provider.output_too_large", "本机桥接图片超过大小限制")
                content.extend(chunk)
            if len(content) <= 8 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ProviderError("provider.invalid_image", "本机桥接输出不是有效的 PNG 图片")
            return ProviderOutput(bytes(content), "image/png", "generated-1.png")

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.core.errors import AppError


@dataclass(frozen=True)
class HermesReply:
    content: str
    response_id: str | None
    session_id: str | None


class HermesClient:
    """Small adapter for Hermes Agent's official OpenAI-compatible gateway."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.hermes_base_url.rstrip("/")

    async def health(self) -> bool:
        if not self.settings.hermes_enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=min(5.0, self.settings.hermes_timeout_seconds)) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.is_success
        except httpx.HTTPError:
            return False

    async def chat(
        self, *, messages: list[dict[str, str]], session_id: str | None = None,
    ) -> HermesReply:
        if not self.settings.hermes_enabled:
            raise AppError("hermes.disabled", "Hermes 智能助理尚未启用，手工工作台不受影响。", 503)
        headers = {
            "Authorization": f"Bearer {self.settings.hermes_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        if session_id:
            headers["X-Hermes-Session-Id"] = session_id
        payload = {
            "model": self.settings.hermes_model,
            "messages": messages,
            "temperature": 0.2,
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.hermes_timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/v1/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise AppError("hermes.timeout", "Hermes 响应超时，请稍后重试；手工操作仍可继续。", 504) from error
        except httpx.HTTPStatusError as error:
            raise AppError("hermes.upstream_error", "Hermes 服务暂时不可用，请稍后重试。", 502, {"status": error.response.status_code}) from error
        except httpx.HTTPError as error:
            raise AppError("hermes.unavailable", "无法连接 Hermes 服务，手工操作仍可继续。", 503) from error
        data = response.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        content = ""
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = str(message.get("content") or "") if isinstance(message, dict) else ""
        if not content.strip():
            raise AppError("hermes.empty_response", "Hermes 没有返回有效内容，请重试。", 502)
        return HermesReply(
            content=content.strip(),
            response_id=str(data.get("id") or "") or None,
            session_id=response.headers.get("X-Hermes-Session-Id") or session_id,
        )

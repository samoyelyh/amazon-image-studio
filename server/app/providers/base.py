from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderOutput:
    content: bytes
    mime_type: str
    filename: str


@dataclass(frozen=True)
class ProviderResult:
    outputs: list[ProviderOutput]
    provider_request_id: str | None = None
    metadata: dict[str, object] | None = None


class ProviderError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable


class BaseImageProvider:
    async def execute(
        self, *, base_url: str, api_key: str, upstream_model: str,
        capability: str, payload: dict[str, object], config: dict[str, object],
    ) -> ProviderResult:
        raise NotImplementedError

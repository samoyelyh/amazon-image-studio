from __future__ import annotations

import base64
from time import perf_counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
        if config.get("image_api_mode") == "responses":
            from app.providers.openai_responses import OpenAIResponsesImageProvider
            return await OpenAIResponsesImageProvider(self.settings).execute(
                base_url=base_url, api_key=api_key, upstream_model=upstream_model,
                capability=capability, payload=payload, config=config,
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
        timeout = _provider_timeout(self.settings)
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
            raise ProviderError(
                "provider.rate_limited" if response.status_code == 429 else "provider.upstream_error",
                message, http_status=response.status_code, retryable=retryable,
                retry_after_seconds=_retry_after_seconds(response),
            )
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
                if payload.get('agent_messages') is not None:
                    parts.append({'type':'text','text':'Reference file: '+str(image.get('filename','image'))})
                parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
            user_content = parts
        request_body: dict[str, object] = {
            "model": upstream_model,
            "messages": [
                {"role": "system", "content": str(payload.get("system_prompt") or "")},
                {"role": "user", "content": user_content},
            ],
            "stream": payload.get('stream') is True,
        }
        # Native agent transcripts retain tool calls/results instead of flattening
        # the session to a single prompt. Only trusted server Jobs set this field.
        if payload.get('agent_messages') is not None:
            import copy
            request_body['messages'] = copy.deepcopy(payload['agent_messages'])
            if references:
                last_user=next((m for m in reversed(request_body['messages']) if m['role']=='user'),None)
                if last_user is not None:
                    original=last_user.get('content') or ''
                    last_user['content']=([{'type':'text','text':original}] if isinstance(original,str) else original)+parts[1:]
            if payload.get('agent_tools'):
                request_body['tools'] = payload['agent_tools']
            if isinstance(payload.get('max_tokens'),int) and 1<=payload['max_tokens']<=12000:
                request_body['max_tokens']=payload['max_tokens']
        response_format = payload.get("response_format", "json_object")
        if response_format == "json_object":
            request_body["response_format"] = {"type": "json_object"}
        elif isinstance(response_format, dict):
            request_body["response_format"] = response_format
        if payload.get("temperature") is not None:
            request_body["temperature"] = payload["temperature"]
        if payload.get('reasoning_effort') is not None:
            effort=payload['reasoning_effort']
            if effort not in {'low','medium','high'}:
                raise ProviderError('provider.invalid_request','Unsupported text reasoning budget',http_status=422)
            request_body['reasoning_effort']=effort
        started=perf_counter()
        stream_metrics={}
        body=None
        try:
            async with httpx.AsyncClient(timeout=_provider_timeout(self.settings), follow_redirects=False) as client:
                if request_body['stream']:
                    async with client.stream('POST',url,headers={'Authorization':f'Bearer {api_key}'},json=request_body) as response:
                        stream_metrics['headers_seconds']=round(perf_counter()-started,3)
                        if response.status_code<400 and 'text/event-stream' in response.headers.get('content-type',''):
                            stream_metrics['response_streamed']=True
                            body,stream_metrics=await _collect_text_stream(response,started,stream_metrics)
                        else:
                            # Some compatible gateways ignore stream and return JSON.
                            # Do not make a fallback second request.
                            stream_metrics['response_streamed']=False
                            await response.aread()
                else:
                    response = await client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=request_body)
        except httpx.TimeoutException as error:
            raise ProviderError("provider.timeout", "Upstream provider timed out", retryable=True) from error
        except httpx.HTTPError as error:
            raise ProviderError("provider.network_error", "Unable to reach upstream provider", retryable=True) from error
        except ProviderError as error:
            error.diagnostics={**_text_response_diagnostics(response,perf_counter()-started,request_body['stream']),**stream_metrics}
            raise
        if response.status_code >= 400:
            retryable = response.status_code in {408, 409, 429} or response.status_code >= 500
            error=ProviderError(
                "provider.rate_limited" if response.status_code == 429 else "provider.upstream_error",
                _error_message(response), http_status=response.status_code, retryable=retryable,
                retry_after_seconds=_retry_after_seconds(response),
            )
            error.diagnostics=_text_response_diagnostics(response,perf_counter()-started,request_body['stream'])
            raise error
        try:
            body = body if body is not None else response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
            text = str(content or '').strip()
            tool_calls = body['choices'][0]['message'].get('tool_calls') or []
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderError("provider.invalid_response", "Upstream provider returned an invalid text response") from error
        if not text and not tool_calls:
            raise ProviderError("provider.empty_result", "Upstream provider returned empty text")
        usage = body.get("usage")
        usage = {key: value for key, value in usage.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)} if isinstance(usage, dict) else None
        raw_usage=body.get('usage')
        details=raw_usage.get('completion_tokens_details') if isinstance(raw_usage,dict) else None
        if isinstance(details,dict) and isinstance(details.get('reasoning_tokens'),int) and not isinstance(details['reasoning_tokens'],bool):
            usage={**(usage or {}),'reasoning_tokens':details['reasoning_tokens']}
        return ProviderResult([], response.headers.get("x-request-id"), {
            "text": text, "created": body.get("created"), "usage": usage,
            **({'tool_calls': tool_calls} if tool_calls else {}),
            'finish_reason':body['choices'][0].get('finish_reason'),
            'transport':{**_text_response_diagnostics(response,perf_counter()-started,request_body['stream']),**stream_metrics},
        })

    async def _download_image(self, url: str, index: int) -> ProviderOutput:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ProviderError("provider.invalid_output_url", "Upstream returned an invalid output URL")
        try:
            async with httpx.AsyncClient(timeout=_provider_timeout(self.settings), follow_redirects=False) as client:
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


def _text_response_diagnostics(response,seconds,stream=False):
    # Explicit allowlist: never retain Authorization, Cookie, raw body or request.
    return {'http_status':response.status_code,'seconds':round(seconds,3),
        'server':response.headers.get('server','')[:80],
        'content_type':response.headers.get('content-type','')[:100],
        'edge_request_id':response.headers.get('cf-ray','')[:100],
        'upstream_request_id':response.headers.get('x-request-id','')[:100],
        'stream':stream,'response_streamed':False}


async def _collect_text_stream(response,started,metrics):
    """Collect one chat completion, never retry a truncated/unknown stream."""
    import json
    pieces=[];characters=0;usage=None;created=None;finish=None;done=False;events=0;calls={}
    async for line in response.aiter_lines():
        if line and 'first_event_seconds' not in metrics:
            metrics['first_event_seconds']=round(perf_counter()-started,3)
        if not line.startswith('data:'):continue
        raw=line[5:].strip()
        if not raw:continue
        if raw=='[DONE]':done=True;break
        try:item=json.loads(raw)
        except ValueError:
            raise ProviderError('provider.network_error','Upstream text stream was incomplete or malformed; outcome unknown',retryable=True) from None
        if not isinstance(item,dict) or item.get('error'):
            raise ProviderError('provider.network_error','Upstream text stream failed; outcome unknown',retryable=True)
        events+=1
        if item.get('usage') is not None:usage=item['usage']
        if item.get('created') is not None:created=item['created']
        for choice in item.get('choices') or []:
            if choice.get('index',0)!=0:continue
            if choice.get('finish_reason') is not None:finish=choice['finish_reason']
            for call in (choice.get('delta') or {}).get('tool_calls') or []:
                current=calls.setdefault(call.get('index',0),{'id':'','type':'function','function':{'name':'','arguments':''}})
                if call.get('id'):current['id']+=call['id']
                for key in ('name','arguments'):
                    current['function'][key]+=(call.get('function') or {}).get(key) or ''
            content=(choice.get('delta') or {}).get('content')
            if isinstance(content,list):content=''.join(str(p.get('text','')) for p in content if isinstance(p,dict))
            if not isinstance(content,str) or not content:continue
            if 'first_text_seconds' not in metrics:metrics['first_text_seconds']=round(perf_counter()-started,3)
            characters+=len(content)
            if characters>100000:
                raise ProviderError('provider.network_error','Upstream text stream exceeded planning boundary; outcome unknown',retryable=True)
            pieces.append(content)
    if not done and finish is None:
        raise ProviderError('provider.network_error','Upstream text stream ended before completion; outcome unknown',retryable=True)
    metrics['events']=events
    return {'choices':[{'message':{'content':''.join(pieces),'tool_calls':[calls[k] for k in sorted(calls)]},'finish_reason':finish}],
        'usage':usage,'created':created},metrics


class CustomImageProvider(OpenAICompatibleProvider):
    """Configurable OpenAI-style adapter for private image gateways."""


def _output(content: bytes, mime_type: str, index: int) -> ProviderOutput:
    if not content:
        raise ProviderError("provider.empty_result", "Upstream provider returned an empty image")
    return ProviderOutput(content, mime_type, f"generated-{index + 1}.png")


def _provider_timeout(settings: Settings) -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.provider_connect_timeout_seconds,
        read=settings.provider_request_timeout_seconds,
        write=min(120.0, settings.provider_request_timeout_seconds),
        pool=settings.provider_connect_timeout_seconds,
    )


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error", body)
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
    except ValueError:
        pass
    return f"Upstream provider returned HTTP {response.status_code}"


def _retry_after_seconds(response: httpx.Response) -> int | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(1, min(3600, int(float(value))))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(1, min(3600, int((target - datetime.now(timezone.utc)).total_seconds())))
        except (TypeError, ValueError, OverflowError):
            return None

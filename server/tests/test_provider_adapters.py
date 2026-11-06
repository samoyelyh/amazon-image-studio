import base64
import json

import httpx

from app.core.config import Settings
from app.providers.openai_compatible import OpenAICompatibleProvider


def install_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr("app.providers.openai_compatible.httpx.AsyncClient", factory)


async def test_text_generation_uses_server_key_and_returns_json_text(monkeypatch) -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        observed["authorization"] = request.headers.get("authorization")
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"product":{"title":"Test"}}'}}]}, headers={"x-request-id": "text-1"})

    install_transport(monkeypatch, handler)
    adapter = OpenAICompatibleProvider(Settings(_env_file=None))
    result = await adapter.execute(
        base_url="https://relay.example/v1", api_key="server-only-secret", upstream_model="chat-model",
        capability="text_generation",
        payload={"system_prompt": "Return JSON", "user_prompt": "Plan listing", "reference_images": [{"content": b"image", "mime_type": "image/png", "filename": "product.png"}]},
        config={},
    )
    assert observed["authorization"] == "Bearer server-only-secret"
    assert observed["body"]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.outputs == [] and result.metadata["text"] == '{"product":{"title":"Test"}}'


async def test_multi_image_edit_uses_multipart_references(monkeypatch) -> None:
    observed = {}
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/edits"
        observed["content_type"] = request.headers.get("content-type")
        observed["body"] = request.content
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]})

    install_transport(monkeypatch, handler)
    adapter = OpenAICompatibleProvider(Settings(_env_file=None))
    result = await adapter.execute(
        base_url="https://relay.example/v1", api_key="server-only-secret", upstream_model="image-model",
        capability="multi_image_reference",
        payload={"prompt": "Put garment on model", "size": "1024x1536", "aspect_ratio": "3:4", "reference_images": [
            {"content": png, "mime_type": "image/png", "filename": "model.png"},
            {"content": png, "mime_type": "image/png", "filename": "garment.png"},
        ]},
        config={
            "edits_endpoint": "/v1/images/edits",
            "edit_body_fields": ["model", "prompt", "aspect_ratio"],
            "edit_dimension_mode": "aspect_ratio",
            "supported_edit_aspect_ratios": ["3:4"],
        },
    )
    assert observed["content_type"].startswith("multipart/form-data;")
    assert b'model.png' in observed["body"] and b'garment.png' in observed["body"]
    assert b'name="model"' in observed["body"] and b'name="prompt"' in observed["body"]
    assert b'name="n"' not in observed["body"] and b'name="size"' not in observed["body"]
    assert b'name="aspect_ratio"' in observed["body"] and b"3:4" in observed["body"]
    assert len(result.outputs) == 1 and result.outputs[0].content == png


async def test_text_usage_is_optional_numeric_metadata_not_an_invoice(monkeypatch):
    def handler(request):
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}],
            'usage':{'prompt_tokens':120,'completion_tokens':40,'total_tokens':160,'debug':'not-token-data','cached':True}})
    install_transport(monkeypatch,handler)
    result=await OpenAICompatibleProvider(Settings(_env_file=None)).execute(base_url='https://relay.example/v1',api_key='test-key',
        upstream_model='test-model',capability='text_generation',payload={'user_prompt':'test'},config={})
    assert result.metadata['usage']=={'prompt_tokens':120,'completion_tokens':40,'total_tokens':160}


async def test_text_524_carries_only_safe_transport_evidence(monkeypatch):
    import pytest
    from app.providers.base import ProviderError
    def handler(request):
        return httpx.Response(524,text='origin timed out',headers={'server':'cloudflare','cf-ray':'test-ray',
            'set-cookie':'secret-cookie','authorization':'secret-header'})
    install_transport(monkeypatch,handler)
    with pytest.raises(ProviderError) as caught:
        await OpenAICompatibleProvider(Settings(_env_file=None)).execute(base_url='https://relay.example/v1',api_key='server-secret',
            upstream_model='test-model',capability='text_generation',payload={'user_prompt':'test'},config={})
    d=caught.value.diagnostics
    assert caught.value.http_status==524 and d['server']=='cloudflare' and d['edge_request_id']=='test-ray'
    assert 'secret' not in json.dumps(d) and d['stream'] is False


async def test_scoped_stream_collects_one_json_reply_and_usage(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content));assert calls[0]['stream'] is True
        chunks=[{'choices':[{'index':0,'delta':{'content':'{"brief":'},'finish_reason':None}]},
            {'choices':[{'index':0,'delta':{'content':'{"ok":true}}'},'finish_reason':None}]},
            {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]},
            {'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}]
        wire=': keepalive\n\n'+''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n'
        return httpx.Response(200,text=wire,headers={'content-type':'text/event-stream','server':'cloudflare'})
    install_transport(monkeypatch,handler)
    value=await OpenAICompatibleProvider(Settings(_env_file=None)).execute(base_url='https://relay.example/v1',api_key='server-secret',
        upstream_model='test-model',capability='text_generation',payload={'user_prompt':'test','stream':True},config={})
    assert json.loads(value.metadata['text'])=={'brief':{'ok':True}}
    assert len(calls)==1 and value.metadata['usage']['total_tokens']==15
    assert value.metadata['transport']['response_streamed'] and 'first_text_seconds' in value.metadata['transport']

async def test_native_tool_call_fragments_keep_assistant_and_tool_history(monkeypatch):
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        assert body['messages'][1]['role']=='tool' and body['messages'][1]['tool_call_id']=='previous'
        assert body['tools'][0]['function']['name']=='produce_aplus'
        chunks=[{'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'id':'native-call','function':{'name':'produce_aplus','arguments':'{"brief":'}}]}}]},
            {'choices':[{'index':0,'delta':{'tool_calls':[{'index':0,'function':{'arguments':'{}}'}}]},'finish_reason':'tool_calls'}]}]
        return httpx.Response(200,text=''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n',headers={'content-type':'text/event-stream'})
    install_transport(monkeypatch,handler)
    value=await OpenAICompatibleProvider(Settings(_env_file=None)).execute(base_url='https://relay.example/v1',api_key='server-secret',upstream_model='test-model',capability='text_generation',
        payload={'stream':True,'response_format':None,'agent_messages':[{'role':'assistant','content':None,'tool_calls':[]},{'role':'tool','tool_call_id':'previous','content':'{}'}],
            'agent_tools':[{'type':'function','function':{'name':'produce_aplus','parameters':{'type':'object'}}}]},config={})
    assert len(calls)==1 and value.metadata['text']==''
    assert json.loads(value.metadata['tool_calls'][0]['function']['arguments'])=={'brief':{}}


async def test_truncated_stream_is_unknown_without_retry(monkeypatch):
    import pytest
    from app.providers.base import ProviderError
    calls=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(200,text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',headers={'content-type':'text/event-stream'})
    install_transport(monkeypatch,handler)
    with pytest.raises(ProviderError) as error:
        await OpenAICompatibleProvider(Settings(_env_file=None)).execute(base_url='https://relay.example/v1',api_key='server-secret',
            upstream_model='test-model',capability='text_generation',payload={'user_prompt':'test','stream':True},config={})
    assert len(calls)==1 and error.value.code=='provider.network_error'
    assert error.value.diagnostics['response_streamed'] is True


async def test_gateway_ignoring_stream_does_not_trigger_second_request(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
    install_transport(monkeypatch,handler)
    value=await OpenAICompatibleProvider(Settings(_env_file=None)).execute(base_url='https://relay.example/v1',api_key='server-secret',
        upstream_model='test-model',capability='text_generation',payload={'user_prompt':'test','stream':True},config={})
    assert len(calls)==1 and value.metadata['transport']['stream'] and not value.metadata['transport']['response_streamed']


async def test_text_reasoning_budget_is_explicit_and_usage_is_numeric(monkeypatch):
    def handler(request):
        body=json.loads(request.content);assert body['reasoning_effort']=='low'
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}],
            'usage':{'completion_tokens':10,'completion_tokens_details':{'reasoning_tokens':3,'debug':'ignore'}}})
    install_transport(monkeypatch,handler)
    value=await OpenAICompatibleProvider(Settings(_env_file=None)).execute(base_url='https://relay.example/v1',api_key='server-secret',
        upstream_model='test-model',capability='text_generation',payload={'user_prompt':'test','reasoning_effort':'low'},config={})
    assert value.metadata['usage']=={'completion_tokens':10,'reasoning_tokens':3}

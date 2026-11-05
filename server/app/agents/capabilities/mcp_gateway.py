"""Per-execution MCP sessions. External descriptions/results never become policy."""
import asyncio
import json
import os
import re
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from app.core.errors import AppError
from app.agents.capabilities.registry import digest


def safe_error(error):
    """Classify transport failures without logging credential-bearing error strings."""
    if isinstance(error, AppError):
        return error.code
    nested = getattr(error, "exceptions", ())
    if nested:
        codes = [safe_error(e) for e in nested]
        return "agent.mcp_auth_failed" if "agent.mcp_auth_failed" in codes else codes[0]
    response = getattr(error, "response", None)
    if getattr(response, "status_code", None) in (401, 403):
        return "agent.mcp_auth_failed"
    import httpx
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return "agent.mcp_timeout"
    if type(error).__name__ == "ToolException":
        return "agent.mcp_tool_failed"
    return "agent.mcp_unavailable"


def charged_units(content):
    """v2 nests the receipt under billing; retain legacy/top-level zero values."""
    if not isinstance(content, dict):
        return None
    value = content.get('chargedUnits')
    billing = content.get('billing')
    return billing.get('chargedUnits') if value is None and isinstance(billing, dict) else value


class MCPGateway:
    def __init__(self, registry):
        self.registry = registry

    def connection(self, server):
        parsed = urlsplit(server.url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise AppError("agent.mcp_url_denied", "MCP地址不可包含凭据、查询参数或片段。", 503)
        if parsed.scheme != "https" and not (server.allow_local_http and parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise AppError("agent.mcp_url_denied", "MCP必须使用管理员批准的HTTPS端点，隔离测试可显式允许本机HTTP。", 503)
        if not parsed.hostname:
            raise AppError("agent.mcp_url_denied", "MCP地址无效。", 503)
        headers = {}
        if server.credential_env:
            credential = os.environ.get(server.credential_env)
            if not credential:
                raise AppError("agent.mcp_auth_missing", "当前获准MCP尚未配置凭据。", 503)
            headers[server.credential_header] = ("Bearer " + credential) if server.credential_header=='Authorization' else credential
        import httpx
        def client_factory(**kwargs):
            # Do not leak approved-server credentials through an implicit system proxy or redirect.
            return httpx.AsyncClient(**kwargs, trust_env=server.trust_environment_proxy, follow_redirects=False)
        return {"url": server.url, "transport": "streamable_http", "headers": headers,
                "httpx_client_factory": client_factory}

    def check_arguments(self, cap, arguments):
        Draft202012Validator.check_schema(cap.input_schema)
        if list(Draft202012Validator(cap.input_schema).iter_errors(arguments)):
            raise AppError("agent.capability_arguments", "工具参数不符合管理员批准的输入约束。", 422)
        # Phase one has public/read-only MCP tools only. Do not transmit private IDs or credentials.
        raw = json.dumps(arguments, ensure_ascii=False)
        if re.search(r"密码|口令|密钥|令牌|(?:password|secret|cookie|authorization)\s*[:=]|\b1[3-9]\d{9}\b|\b\d{17}[\dX]\b", raw, re.I):
            raise AppError("agent.mcp_sensitive_input", "公开查询中检测到可能的敏感内容，已阻止外发。", 403)
        if len(raw) > 8000 or re.search(r"(?:sk-[A-Za-z0-9]{12,}|Bearer\s+\S+|[a-f0-9]{8}-[a-f0-9-]{27,}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", raw, re.I):
            raise AppError("agent.mcp_sensitive_input", "当前MCP仅允许公开查询，不可传递密钥、私有对象ID或敏感信息。", 403)
        if any(re.search(r"password|secret|token|cookie|authorization|asset_id|prompt|image|phone|email", str(k), re.I) for k in arguments):
            raise AppError("agent.mcp_sensitive_input", "该MCP调用包含未获准的数据字段。", 403)

    async def discover(self, server):
        """Metadata only: tools/list, never tools/call. No model fee or data research."""
        from langchain_mcp_adapters.client import MultiServerMCPClient
        async def listing():
            client=MultiServerMCPClient({server.id:self.connection(server)},handle_tool_errors=False)
            async with client.session(server.id) as session:
                tools, cursors, cursor = [], set(), None
                for _ in range(10):
                    result = await session.list_tools(cursor=cursor) if cursor else await session.list_tools()
                    tools.extend({'name':t.name,'input_schema':t.inputSchema} for t in result.tools)
                    if len(tools) > 500:
                        raise AppError('agent.mcp_catalog_limit','工具目录过大，未执行调研。',503)
                    cursor = getattr(result, 'nextCursor', None)
                    if not cursor:
                        if len({t['name'] for t in tools}) != len(tools):
                            raise AppError('agent.mcp_catalog_invalid','工具目录含重名项，需管理员核对。',503)
                        return tools
                    if cursor in cursors:
                        raise AppError('agent.mcp_catalog_invalid','工具分页游标重复，未执行调研。',503)
                    cursors.add(cursor)
                raise AppError('agent.mcp_catalog_limit','工具目录分页超限，未执行调研。',503)
        try:return await asyncio.wait_for(listing(),server.timeout_seconds)
        except Exception as error:raise AppError(safe_error(error),'MCP工具发现失败，未执行调研。',503) from None

    async def call(self, cap, arguments, *, calls_used, charge_confirmed=False):
        # Identity and tool lookup are repeated at call time; no model-selected endpoint/headers.
        current = self.registry.get(cap.id)
        server = self.registry.mcp[current.binding]
        if current.source != "mcp" or current.risk != "read_only" or (current.may_charge and not (charge_confirmed and server.profile=='sellersprite')):
            raise AppError("agent.mcp_risk_not_enabled", "首期MCP只启用获准的无费用只读工具。", 403)
        server = self.registry.mcp[current.binding]
        if calls_used >= server.max_calls_per_run:
            raise AppError("agent.mcp_budget_exhausted", "本次Run的MCP调用预算已用完，不会继续请求。", 409)
        self.check_arguments(current, arguments)
        connection = self.connection(server)

        async def invoke():
            from langchain_mcp_adapters.client import MultiServerMCPClient
            from langchain_mcp_adapters.tools import load_mcp_tools
            client = MultiServerMCPClient({server.id: connection}, handle_tool_errors=False)
            async with client.session(server.id) as session:
                tools = await load_mcp_tools(session, handle_tool_errors=False)
                name = current.id.split(".", 2)[2]
                tool = next((t for t in tools if t.name == name), None)
                if tool is None:
                    raise AppError("agent.mcp_tool_missing", "获准的MCP工具当前未被服务端发现。", 503)
                schema = tool.args_schema if isinstance(tool.args_schema, dict) else tool.args_schema.model_json_schema()
                if digest(schema) != digest(current.input_schema):
                    raise AppError("agent.mcp_schema_changed", "MCP输入协议已变化，需管理员重新审核，未调用工具。", 409)
                if server.profile=='sellersprite':
                    raw=await session.call_tool(name,arguments)
                    if raw.isError:raise AppError('agent.mcp_tool_failed','卖家精灵返回工具错误，费用状态需要核对。',503)
                    from app.services.hermes_agent_service import audit_safe_snapshot
                    content=raw.structuredContent
                    if content is None:
                        texts=[c.text for c in raw.content if getattr(c,'type',None)=='text']
                        try:content=json.loads('\n'.join(texts))
                        except ValueError:content={'text':'\n'.join(texts)}
                    if len(json.dumps(content,ensure_ascii=False))>100000:
                        raise AppError('agent.mcp_result_too_large','结果过大，已停止；勿自动重试收费查询。',503)
                    return {'trust':'untrusted_external_data','content':audit_safe_snapshot(content),
                        'chargedUnits':charged_units(content)}
                value = await tool.ainvoke(arguments)
                if hasattr(value, "content"):
                    value = value.content
                text = json.dumps(value, ensure_ascii=False, default=lambda _: "[unsupported content]")
                if len(text) > 12000:
                    return {"trust": "untrusted_external_data", "truncated": True, "content": text[:12000]}
                return {"trust": "untrusted_external_data", "truncated": False, "content": value}
        try:
            return await asyncio.wait_for(invoke(), timeout=server.timeout_seconds)
        except AppError:
            raise
        except ImportError:
            raise AppError("agent.mcp_dependency_missing", "当前环境未安装可选MCP适配器。", 503) from None
        except Exception as error:
            code = safe_error(error)
            raise AppError(code, "MCP连接、认证或调用失败；未自动切换至未批准服务。", 503) from None

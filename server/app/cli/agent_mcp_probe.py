"""Server-admin metadata probe. Never tools/call, model inference or configuration writes."""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from app.agents.amazon_research import ALLOWED_TOOLS
from app.agents.capabilities.contracts import CapabilityManifest
from app.agents.capabilities.mcp_gateway import MCPGateway, safe_error
from app.agents.capabilities.registry import digest
from app.core.config import get_settings
from app.core.errors import AppError


async def probe(settings, server_id, organization_id, user_id):
    path = settings.agent_capability_manifest
    if not path:
        raise AppError('agent.registry_missing', '网站未配置AGENT_CAPABILITY_MANIFEST。', 503)
    try:
        file = Path(path)
        if file.stat().st_size > 131072:
            raise ValueError('size')
        manifest = CapabilityManifest.model_validate_json(file.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        raise AppError('agent.registry_invalid', '网站能力审批配置无效。', 503) from None
    server = next((s for s in manifest.mcp_servers if s.id == server_id), None)
    if not server or organization_id not in server.organizations or (server.users and user_id not in server.users):
        raise AppError('agent.mcp_not_authorized', '该组织或用户未获准访问此MCP。', 403)
    # Disabled entries may be inspected by the server administrator before enabling.
    # This command has no mechanism for tool execution or credential input arguments.
    if server.profile != 'sellersprite':
        raise AppError('agent.mcp_profile', '此检查命令仅用于卖家精灵。', 422)
    if not server.credential_env or not os.environ.get(server.credential_env):
        raise AppError('agent.mcp_auth_missing', '请在网站服务端配置credential_env对应的凭据。', 503)
    discovered = await MCPGateway(None).discover(server)
    approved = {t.name:t for t in server.tools}
    actual = {t['name']:t for t in discovered}
    matches = []
    for name in sorted(ALLOWED_TOOLS):
        found, configured = actual.get(name), approved.get(name)
        matches.append({'candidate':name, 'discovered':found is not None,
            'approved':configured is not None,
            'schema_matches':digest(found['input_schema']) == digest(configured.input_schema) if found and configured else None,
            'input_schema':found['input_schema'] if found else None})
    return {'server_id':server.id, 'enabled':server.enabled, 'transport':'streamable_http',
        'credential_header':server.credential_header, 'profile':server.profile,
        'timeout_seconds':server.timeout_seconds, 'daily_unit_limit':server.daily_unit_limit,
        'calls_per_minute':server.calls_per_minute, 'max_calls_per_run':server.max_calls_per_run,
        'tools_list_succeeded':True, 'tools_call_count':0, 'research_executed':False,
        'trust':'untrusted_external_metadata_not_instructions', 'candidates':matches,
        'other_discovered_names':sorted(set(actual)-ALLOWED_TOOLS),
        'note':'不自动修改白名单或Schema。名称不同须人工核对语义和计费后再映射。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-id', required=True)
    parser.add_argument('--organization-id', required=True)
    parser.add_argument('--user-id', required=True)
    args = parser.parse_args()
    # SDK errors may contain endpoint/headers; only our stable error codes are output.
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(probe(get_settings(), args.server_id, args.organization_id, args.user_id))
    except Exception as error:
        print(json.dumps({'tools_list_succeeded':False, 'tools_call_count':0, 'error_code':safe_error(error)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

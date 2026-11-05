"""Sellersprite v2 billing compatibility; no remote calls."""
import json
from pathlib import Path

import pytest
from app.agents.capabilities.contracts import CapabilityManifest, ExecutionContext
from app.agents.capabilities.registry import CapabilityRegistry, ToolSelector
from app.agents.capabilities.mcp_gateway import charged_units
from app.core.config import Settings
from app.core.errors import AppError


@pytest.mark.parametrize('content,expected', [
    ({'chargedUnits': 1}, 1), ({'chargedUnits': 0, 'billing': {'chargedUnits': 3}}, 0),
    ({'billing': {'chargedUnits': 2, 'remainingUnits': 50}}, 2),
    ({'billing': {'chargedUnits': 0}}, 0), ({'billing': {}}, None),
    ({'billing': None}, None), ({}, None), ([], None), ('bad', None),
    ({'billing': {'chargedUnits': 'unknown'}}, 'unknown'),
])
def test_billing_v2_does_not_report_unknown_as_free(content, expected):
    assert charged_units(content) == expected


def test_legacy_real_data_and_unknown_billing_are_independent():
    from app.agents.amazon_research import usable_data
    assert usable_data({'status':'needs_review','chargedUnits':None,'content':{'items':[{'asin':'B0716YP6VJ'}]}})
    assert not usable_data({'status':'unknown','content':{'items':[]}})
    assert not usable_data({'status':'needs_review','over_budget':True,'content':{'items':[1]}})


def test_ss_mcp_real_schema_manifest_scope_and_selection():
    path = Path(__file__).resolve().parents[1] / 'config' / 'ss-mcp.approval.json'
    manifest = CapabilityManifest.model_validate_json(path.read_text(encoding='utf-8'))
    server = manifest.mcp_servers[0]
    assert server.enabled and server.id == 'ss_mcp'
    assert server.credential_header == 'secret-key' and server.profile == 'sellersprite'
    assert server.credential_env == 'AGENT_MCP_SS_MCP_SECRET'
    from app.agents.amazon_research import ALLOWED_TOOLS
    assert {t.name for t in server.tools} == ALLOWED_TOOLS
    assert next(t for t in server.tools if t.name == 'asin.review.list').max_charge_units == 5
    settings = Settings(_env_file=None, agent_capability_manifest=str(path))
    ctx = ExecutionContext(server.organizations[0], 'test-user', 'test-chat', 'test-run', frozenset({'jobs.read'}))
    registry = CapabilityRegistry(settings, ctx)
    for name in ALLOWED_TOOLS:
        assert registry.get('mcp.ss_mcp.'+name).may_charge
    selected = ToolSelector.select(registry, 'Amazon ASIN竞品市场调研和评论关键词', primary_skills=['amazon-market-insight'])
    assert any(t['id'].startswith('mcp.ss_mcp.') for t in selected['tools'])
    other = CapabilityRegistry(settings, ExecutionContext('other-org', 'test-user', 'chat', 'run', ctx.permissions))
    with pytest.raises(AppError):
        other.get('mcp.ss_mcp.asin.detail')
    assert 'secret-key' not in json.dumps(server.model_dump().get('tools'))

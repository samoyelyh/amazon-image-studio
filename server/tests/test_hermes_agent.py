from datetime import datetime, timezone

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.clients.hermes_client import HermesReply
from app.core.config import Settings
from app.core.errors import AppError
from app.models.hermes_agent import HermesToolAudit
from app.models.identity import User
from app.models.listing_workflow import CategorySkill, ListingGenerationSession, ListingImageProject, ListingVersion, ProductCategory
from app.services.hermes_agent_service import (
    apply_hermes_proposal,
    audit_safe_snapshot,
    get_or_create_conversation,
    parse_hermes_response,
    send_hermes_message,
)
from app.services.hermes_tool_registry import execute_hermes_tool, load_hermes_workbench_context, tool_catalog


async def _project(context: dict[str, object]) -> tuple[str, str]:
    async with context["session_factory"]() as db:
        user = await db.scalar(select(User).where(User.account == "first-admin"))
        category = ProductCategory(category_code="football_jersey", category_name="橄榄球衣")
        db.add(category); await db.flush()
        skill = CategorySkill(
            category_id=category.id, skill_name="默认Skill", skill_code="hermes-test", version=1,
            analysis_prompt="analysis", listing_title_prompt="title", bullet_points_prompt="bullets",
            a_plus_prompt="a+", image_prompt_template="image", image_types_config=[], prompt_rules={},
        )
        db.add(skill); await db.flush()
        workflow = ListingGenerationSession(
            organization_id=context["first_org"], category_id=category.id, skill_id=skill.id,
            category_skill_snapshot={"category_code": "football_jersey", "category_name": "橄榄球衣", "skill_name": "默认Skill", "skill_version": 1},
            status="confirmed", source_asset_ids=[], listing_content={"title": {"zh": "测试球衣"}},
            confirmed_at=datetime.now(timezone.utc), confirmed_by=user.id,
            created_by=user.id, updated_by=user.id,
        )
        db.add(workflow); await db.flush()
        version = ListingVersion(
            organization_id=context["first_org"], session_id=workflow.id, version_number=1,
            listing_snapshot={"title_cn": "测试球衣"}, analysis_snapshot={"main_color": "红色"},
            category_skill_snapshot=dict(workflow.category_skill_snapshot),
            confirmed_at=datetime.now(timezone.utc), confirmed_by=user.id, created_by=user.id,
        )
        db.add(version); await db.flush()
        workflow.current_listing_version_id = version.id
        project = ListingImageProject(
            organization_id=context["first_org"], session_id=workflow.id, listing_version_id=version.id,
            status="editing", prompt_config={}, created_by=user.id, updated_by=user.id,
        )
        db.add(project); await db.commit()
        return project.id, user.id


def test_hermes_parser_rejects_unknown_and_implicit_expensive_actions() -> None:
    _, unknown = parse_hermes_response(
        '{"reply":"好","proposal":{"summary":"运行Shell","actions":[{"tool":"run_shell","arguments":{}}]}}',
        user_text="帮我看看",
    )
    assert unknown is None
    _, implicit = parse_hermes_response(
        '{"reply":"好","proposal":{"summary":"生成图片","actions":[{"tool":"generate_modules","arguments":{"module_keys":["pure_white"]}}]}}',
        user_text="现在准备好了吗",
    )
    assert implicit is None
    _, explicit = parse_hermes_response(
        '{"reply":"可以","proposal":{"summary":"生成图片","actions":[{"tool":"generate_modules","arguments":{"module_keys":["pure_white"]}}]}}',
        user_text="请生成纯白底图",
    )
    assert explicit and explicit["actions"][0]["tool"] == "generate_modules"


def test_hermes_tool_catalog_declares_risk_permission_and_redacts_audit_secrets() -> None:
    catalog = {item["name"]: item for item in tool_catalog()}
    assert catalog["generate_modules"]["risk_level"] == "EXPENSIVE_ACTION"
    assert catalog["generate_modules"]["required_permission"] == "jobs.submit"
    assert catalog["get_product_context"]["risk_level"] == "READ_ONLY"
    snapshot = audit_safe_snapshot({
        "api_key": "hidden", "instruction": "Authorization: Bearer secret-value sk-1234567890123456",
    })
    assert "hidden" not in str(snapshot)
    assert "secret-value" not in str(snapshot)
    assert "sk-1234567890123456" not in str(snapshot)


@pytest.mark.asyncio
async def test_hermes_tool_registry_enforces_current_user_permission(identity_test_context) -> None:
    project_id, user_id = await _project(identity_test_context)
    async with identity_test_context["session_factory"]() as db:
        context = await load_hermes_workbench_context(
            db, organization_id=identity_test_context["first_org"], project_id=project_id, user_id=user_id,
        )
        with pytest.raises(AppError) as denied:
            await execute_hermes_tool(
                db, Settings(), context=context, tool_name="generate_modules",
                arguments={"module_keys": ["pure_white"]}, user_id=user_id,
                permissions=frozenset({"jobs.read"}),
            )
        assert denied.value.code == "auth.permission_denied"


@pytest.mark.asyncio
async def test_hermes_conversation_is_user_scoped_and_proposal_is_audited(identity_test_context, monkeypatch) -> None:
    project_id, user_id = await _project(identity_test_context)
    settings = Settings(hermes_enabled=True, hermes_api_key=SecretStr("test-hermes-key"))

    async def fake_chat(self, *, messages, session_id=None):
        assert messages[0]["role"] == "system"
        assert "数据库" in messages[0]["content"]
        return HermesReply(
            content='{"reply":"我建议记录这条反馈。","proposal":{"summary":"记录运营反馈","actions":[{"tool":"record_feedback","arguments":{"feedback":"礼品图更温暖"}}]}}',
            response_id="response-test", session_id="session-test",
        )

    monkeypatch.setattr("app.clients.hermes_client.HermesClient.chat", fake_chat)
    async with identity_test_context["session_factory"]() as db:
        context = await load_hermes_workbench_context(
            db, organization_id=identity_test_context["first_org"], project_id=project_id, user_id=user_id,
        )
        conversation = await get_or_create_conversation(
            db, organization_id=identity_test_context["first_org"], user_id=user_id, project_id=project_id,
        )
        message, proposal = await send_hermes_message(
            db, settings, conversation=conversation,
            organization_id=identity_test_context["first_org"], user_id=user_id,
            project_id=project_id, content="请记录反馈：礼品图更温暖",
        )
        assert message.role == "assistant"
        assert proposal and proposal.status == "pending"
        results, signature = await apply_hermes_proposal(
            db, settings, proposal=proposal,
            organization_id=identity_test_context["first_org"], user_id=user_id,
            permissions=frozenset({"jobs.read"}),
        )
        assert results[0]["tool"] == "record_feedback"
        assert len(signature) == 64
        audit = await db.scalar(select(HermesToolAudit).where(HermesToolAudit.proposal_id == proposal.id))
        assert audit and audit.status == "succeeded"
        assert "test-hermes-key" not in str(audit.arguments_json)

        second_conversation = await get_or_create_conversation(
            db, organization_id=identity_test_context["first_org"], user_id=user_id,
            project_id=project_id, title="second",
        )
        # The active conversation is deliberately reused for this user/project.
        assert second_conversation.id == conversation.id

        viewer = await db.scalar(select(User).where(User.account == "first-viewer"))
        viewer_conversation = await get_or_create_conversation(
            db, organization_id=identity_test_context["first_org"], user_id=viewer.id,
            project_id=project_id,
        )
        assert viewer_conversation.id != conversation.id
        with pytest.raises(AppError) as cross_user:
            await apply_hermes_proposal(
                db, settings, proposal=proposal,
                organization_id=identity_test_context["first_org"], user_id=viewer.id,
                permissions=frozenset({"jobs.read"}),
            )
        assert cross_user.value.code == "hermes.proposal_not_found"

        _message, stale_proposal = await send_hermes_message(
            db, settings, conversation=conversation,
            organization_id=identity_test_context["first_org"], user_id=user_id,
            project_id=project_id, content="请记录反馈：构图更紧凑",
        )
        assert stale_proposal and stale_proposal.status == "pending"
        context.plan.state_version += 1
        await db.commit()
        with pytest.raises(AppError) as stale:
            await apply_hermes_proposal(
                db, settings, proposal=stale_proposal,
                organization_id=identity_test_context["first_org"], user_id=user_id,
                permissions=frozenset({"jobs.read", "jobs.submit"}),
            )
        assert stale.value.code == "hermes.proposal_stale"
        assert stale_proposal.status == "stale"


@pytest.mark.asyncio
async def test_hermes_status_disabled_does_not_break_workbench(identity_test_context) -> None:
    project_id, _ = await _project(identity_test_context)
    client = identity_test_context["client"]
    login = await client.post("/api/v1/auth/login", json={"account": "first-admin", "password": "correct-password"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/hermes/status", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    planning = await client.get(f"/api/v1/attachment-workbench/projects/{project_id}/planning", headers=headers)
    assert planning.status_code == 200

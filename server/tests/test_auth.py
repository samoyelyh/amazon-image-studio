from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.models.identity import AuditLog, LoginAudit, RefreshToken


async def login(client: AsyncClient, email: str, password: str) -> dict[str, object]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


async def test_login_me_and_refresh_rotation(identity_test_context) -> None:
    client = identity_test_context["client"]
    payload = await login(client, "FIRST-ADMIN@EXAMPLE.COM", "correct-password")
    assert payload["token_type"] == "bearer"
    assert payload["identity"]["organization"]["slug"] == "first-team"
    assert "organization.members.write" in payload["identity"]["permissions"]
    old_refresh = client.cookies["ais_refresh_token"]

    me_response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["user"]["email"] == "first-admin@example.com"

    refresh_response = await client.post("/api/v1/auth/refresh")
    assert refresh_response.status_code == 200
    assert client.cookies["ais_refresh_token"] != old_refresh

    async with identity_test_context["session_factory"]() as session:
        tokens = list((await session.scalars(select(RefreshToken).order_by(RefreshToken.created_at))).all())
        assert len(tokens) == 2
        assert tokens[0].revoked_at is not None
        assert tokens[0].replaced_by_token_id == tokens[1].id
        assert tokens[0].token_hash != old_refresh


async def test_refresh_token_reuse_revokes_the_whole_family(identity_test_context) -> None:
    client = identity_test_context["client"]
    await login(client, "first-admin@example.com", "correct-password")
    reused_secret = client.cookies["ais_refresh_token"]
    successful_refresh = await client.post("/api/v1/auth/refresh")
    assert successful_refresh.status_code == 200
    newest_secret = client.cookies["ais_refresh_token"]

    async with AsyncClient(
        transport=ASGITransport(app=identity_test_context["app"]),
        base_url="http://test",
        cookies={"ais_refresh_token": reused_secret},
    ) as replay_client:
        replay = await replay_client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "auth.refresh_token_reused"

    newest_after_replay = await client.post("/api/v1/auth/refresh")
    assert newest_after_replay.status_code == 401
    assert newest_after_replay.json()["error"]["code"] == "auth.refresh_token_reused"


async def test_invalid_login_is_generic_and_audited(identity_test_context) -> None:
    client = identity_test_context["client"]
    response = await client.post(
        "/api/v1/auth/login", json={"email": "first-admin@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_credentials"

    async with identity_test_context["session_factory"]() as session:
        audit = await session.scalar(select(LoginAudit).order_by(LoginAudit.created_at.desc()))
        assert audit is not None
        assert audit.outcome == "failure"
        assert audit.detail == "invalid_credentials"


async def test_viewer_cannot_read_members(identity_test_context) -> None:
    client = identity_test_context["client"]
    payload = await login(client, "first-viewer@example.com", "viewer-password")
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    organization_response = await client.get("/api/v1/organizations/current", headers=headers)
    members_response = await client.get("/api/v1/organizations/current/members", headers=headers)
    assert organization_response.status_code == 200
    assert members_response.status_code == 403
    assert members_response.json()["error"]["code"] == "auth.permission_denied"


async def test_organization_admin_cannot_mutate_another_team(identity_test_context) -> None:
    client = identity_test_context["client"]
    payload = await login(client, "first-admin@example.com", "correct-password")
    response = await client.delete(
        f"/api/v1/organizations/current/members/{identity_test_context['second_admin_membership']}",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.organization_access_denied"


async def test_last_organization_admin_cannot_be_demoted(identity_test_context) -> None:
    client = identity_test_context["client"]
    payload = await login(client, "first-admin@example.com", "correct-password")
    response = await client.patch(
        f"/api/v1/organizations/current/members/{identity_test_context['first_admin_membership']}/role",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
        json={"role_code": "viewer"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "organization.last_admin"


async def test_add_member_creates_audit_log(identity_test_context) -> None:
    client = identity_test_context["client"]
    payload = await login(client, "first-admin@example.com", "correct-password")
    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    response = await client.post(
        "/api/v1/organizations/current/members",
        headers=headers,
        json={
            "email": "new-member@example.com",
            "display_name": "New Member",
            "temporary_password": "temporary-password",
            "role_code": "member",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"]["code"] == "member"

    logs_response = await client.get("/api/v1/audit-logs", headers=headers)
    assert logs_response.status_code == 200
    assert logs_response.json()["items"][0]["action"] == "organization.member.add"
    login_logs_response = await client.get("/api/v1/audit-logs/logins", headers=headers)
    assert login_logs_response.status_code == 200
    assert login_logs_response.json()["items"][0]["event"] == "login"

    async with identity_test_context["session_factory"]() as session:
        count = await session.scalar(select(func.count()).select_from(AuditLog))
        assert count == 1

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.models.identity import AuditLog, LoginAudit, OrganizationMember, RefreshToken, Role, User


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
            "temporary_password": "N7!vK2@qR8#z",
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


async def test_member_creation_is_idempotent_and_requires_unique_email(identity_test_context) -> None:
    client = identity_test_context["client"]
    payload = await login(client, "first-admin@example.com", "correct-password")
    headers = {
        "Authorization": f"Bearer {payload['access_token']}",
        "Idempotency-Key": "create-user-replay-001",
    }
    body = {
        "email": "idempotent@example.com",
        "display_name": "Idempotent User",
        "temporary_password": "R8@tY4!mQ2#v",
        "role_code": "member",
    }
    first = await client.post("/api/v1/organizations/current/members", headers=headers, json=body)
    replay = await client.post("/api/v1/organizations/current/members", headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["user"]["must_change_password"] is True

    conflict = await client.post(
        "/api/v1/organizations/current/members",
        headers={**headers, "Idempotency-Key": "create-user-replay-002"},
        json=body,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "organization.user_email_exists"


async def test_forced_password_change_blocks_business_and_rotates_sessions(identity_test_context) -> None:
    admin_client = identity_test_context["client"]
    admin = await login(admin_client, "first-admin@example.com", "correct-password")
    create = await admin_client.post(
        "/api/v1/organizations/current/members",
        headers={
            "Authorization": f"Bearer {admin['access_token']}",
            "Idempotency-Key": "forced-password-user-001",
        },
        json={
            "email": "forced-change@example.com",
            "display_name": "Forced Change",
            "temporary_password": "V7!qM3@rT9#x",
            "role_code": "member",
        },
    )
    assert create.status_code == 201, create.text

    async with AsyncClient(
        transport=ASGITransport(app=identity_test_context["app"]),
        base_url="http://test",
    ) as user_client:
        signed_in = await login(user_client, "forced-change@example.com", "V7!qM3@rT9#x")
        old_access = signed_in["access_token"]
        assert signed_in["identity"]["user"]["must_change_password"] is True
        me = await user_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"}
        )
        blocked = await user_client.get(
            "/api/v1/organizations/current", headers={"Authorization": f"Bearer {old_access}"}
        )
        assert me.status_code == 200
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "auth.password_change_required"

        changed = await user_client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {old_access}"},
            json={"current_password": "V7!qM3@rT9#x", "new_password": "K6@pW8!zN4$q"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["identity"]["user"]["must_change_password"] is False
        stale = await user_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"}
        )
        assert stale.status_code == 401
        assert stale.json()["error"]["code"] == "auth.session_revoked"
        current = await user_client.get(
            "/api/v1/organizations/current",
            headers={"Authorization": f"Bearer {changed.json()['access_token']}"},
        )
        assert current.status_code == 200

    old_login = await admin_client.post(
        "/api/v1/auth/login",
        json={"email": "forced-change@example.com", "password": "V7!qM3@rT9#x"},
    )
    new_login = await admin_client.post(
        "/api/v1/auth/login",
        json={"email": "forced-change@example.com", "password": "K6@pW8!zN4$q"},
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


async def test_reset_password_invalidates_access_and_does_not_audit_secret(identity_test_context) -> None:
    client = identity_test_context["client"]
    target = await login(client, "first-viewer@example.com", "viewer-password")
    old_access = target["access_token"]
    old_refresh = client.cookies["ais_refresh_token"]
    admin = await login(client, "first-admin@example.com", "correct-password")
    reset = await client.post(
        f"/api/v1/organizations/current/members/{identity_test_context['first_viewer_membership']}/reset-password",
        headers={"Authorization": f"Bearer {admin['access_token']}"},
        json={"temporary_password": "J9!sC4@uL7#n", "force_change_password": True},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["must_change_password"] is True
    stale = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access}"})
    assert stale.status_code == 401

    async with AsyncClient(
        transport=ASGITransport(app=identity_test_context["app"]), base_url="http://test"
    ) as password_client:
        old_password = await password_client.post(
            "/api/v1/auth/login",
            json={"email": "first-viewer@example.com", "password": "viewer-password"},
        )
        new_password = await password_client.post(
            "/api/v1/auth/login",
            json={"email": "first-viewer@example.com", "password": "J9!sC4@uL7#n"},
        )
    assert old_password.status_code == 401
    assert new_password.status_code == 200
    assert new_password.json()["identity"]["user"]["must_change_password"] is True

    async with AsyncClient(
        transport=ASGITransport(app=identity_test_context["app"]),
        base_url="http://test",
        cookies={"ais_refresh_token": old_refresh},
    ) as refresh_client:
        stale_refresh = await refresh_client.post("/api/v1/auth/refresh")
    assert stale_refresh.status_code == 401

    async with identity_test_context["session_factory"]() as session:
        user = await session.scalar(select(User).where(User.email == "first-viewer@example.com"))
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "organization.member.password_reset")
        )
        assert user is not None and user.must_change_password is True
        assert audit is not None
        assert "J9!sC4@uL7#n" not in str(audit.metadata_json)


async def test_member_role_cannot_create_users(identity_test_context) -> None:
    async with identity_test_context["session_factory"]() as session:
        role = await session.scalar(select(Role).where(Role.code == "member"))
        membership = await session.get(OrganizationMember, identity_test_context["first_viewer_membership"])
        membership.role_id = role.id
        await session.commit()

    client = identity_test_context["client"]
    signed_in = await login(client, "first-viewer@example.com", "viewer-password")
    response = await client.post(
        "/api/v1/organizations/current/members",
        headers={"Authorization": f"Bearer {signed_in['access_token']}"},
        json={
            "email": "forbidden-create@example.com",
            "display_name": "Forbidden Create",
            "temporary_password": "H8!mR3@qV6#z",
            "role_code": "member",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.permission_denied"

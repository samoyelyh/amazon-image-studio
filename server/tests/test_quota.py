from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.models.quota import QuotaAccount, QuotaReservation, QuotaTransaction
from app.services.billing_service import refund_reservation, release_reservation, reserve_quota, settle_reservation


async def auth_headers(client, account: str, password: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"account": account, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_cost_estimate_uses_server_rules_and_multipliers(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "first-admin", "correct-password")
    response = await client.post("/api/v1/quota/estimate", headers=headers, json={
        "operation_code": "listing.generate",
        "quantity": 2,
        "model": "premium",
        "quality": "high",
        "resolution": "2048",
        "resource_pool": "platform",
    })
    assert response.status_code == 200, response.text
    estimate = response.json()
    assert estimate["unit_cost"] == 60
    assert estimate["estimated_cost"] == 120
    assert estimate["available_balance"] == 1000
    assert estimate["sufficient"] is True


async def test_personal_resource_pool_can_be_configured_as_free(identity_test_context) -> None:
    client = identity_test_context["client"]
    headers = await auth_headers(client, "first-admin", "correct-password")
    response = await client.post("/api/v1/quota/estimate", headers=headers, json={
        "operation_code": "listing.generate", "quantity": 20, "resource_pool": "personal",
    })
    assert response.status_code == 200
    assert response.json()["estimated_cost"] == 0


async def test_insufficient_quota_does_not_create_reservation(identity_test_context) -> None:
    settings = Settings(_env_file=None)
    async with identity_test_context["session_factory"]() as session:
        try:
            await reserve_quota(
                session, settings,
                organization_id=identity_test_context["second_org"], user_id="system",
                operation_code="listing.generate", quantity=6, factors={}, idempotency_key="insufficient-001",
            )
        except AppError as error:
            assert error.code == "quota.insufficient"
            assert error.status_code == 402
        else:
            raise AssertionError("reservation should have failed")
        assert await session.scalar(select(QuotaReservation.id).where(
            QuotaReservation.organization_id == identity_test_context["second_org"]
        )) is None


async def test_reservation_and_partial_settlement_are_idempotent(identity_test_context) -> None:
    settings = Settings(_env_file=None)
    async with identity_test_context["session_factory"]() as session:
        reservation = await reserve_quota(
            session, settings,
            organization_id=identity_test_context["first_org"], user_id=None,
            operation_code="listing.generate", quantity=5, factors={}, idempotency_key="batch-partial-001",
            reference_type="batch", reference_id="batch-1",
        )
        duplicate = await reserve_quota(
            session, settings,
            organization_id=identity_test_context["first_org"], user_id=None,
            operation_code="listing.generate", quantity=5, factors={}, idempotency_key="batch-partial-001",
            reference_type="batch", reference_id="batch-1",
        )
        assert duplicate.id == reservation.id
        await session.commit()

    async with identity_test_context["session_factory"]() as session:
        settled = await settle_reservation(
            session, organization_id=identity_test_context["first_org"], reservation_id=reservation.id,
            user_id=None, actual_quantity=3, idempotency_key="settle-partial-001",
        )
        repeated = await settle_reservation(
            session, organization_id=identity_test_context["first_org"], reservation_id=reservation.id,
            user_id=None, actual_quantity=3, idempotency_key="settle-partial-001",
        )
        assert repeated.id == settled.id
        await session.commit()

    async with identity_test_context["session_factory"]() as session:
        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == identity_test_context["first_org"]))
        assert account.balance == 970
        assert account.reserved_balance == 0
        stored = await session.get(QuotaReservation, reservation.id)
        assert stored.status == "partially_consumed"
        assert stored.consumed_amount == 30
        assert stored.released_amount == 20
        transactions = list((await session.scalars(select(QuotaTransaction).where(
            QuotaTransaction.reservation_id == reservation.id
        ))).all())
        assert sorted(item.transaction_type for item in transactions) == ["consume", "release", "reserve"]


async def test_failed_reservation_release_and_refund(identity_test_context) -> None:
    settings = Settings(_env_file=None)
    async with identity_test_context["session_factory"]() as session:
        failed = await reserve_quota(
            session, settings, organization_id=identity_test_context["first_org"], user_id=None,
            operation_code="listing.generate", quantity=2, factors={}, idempotency_key="failed-001",
        )
        await session.commit()
    async with identity_test_context["session_factory"]() as session:
        released = await release_reservation(
            session, organization_id=identity_test_context["first_org"], reservation_id=failed.id,
            user_id=None, idempotency_key="release-failed-001",
        )
        assert released.status == "released"
        await session.commit()

        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == identity_test_context["first_org"]))
        assert account.balance == 1000
        assert account.reserved_balance == 0

    async with identity_test_context["session_factory"]() as session:
        successful = await reserve_quota(
            session, settings, organization_id=identity_test_context["first_org"], user_id=None,
            operation_code="listing.generate", quantity=2, factors={}, idempotency_key="success-refund-001",
        )
        await session.commit()
    async with identity_test_context["session_factory"]() as session:
        await settle_reservation(
            session, organization_id=identity_test_context["first_org"], reservation_id=successful.id,
            user_id=None, actual_quantity=2, idempotency_key="settle-success-001",
        )
        refunded = await refund_reservation(
            session, organization_id=identity_test_context["first_org"], reservation_id=successful.id,
            user_id=None, amount=20, idempotency_key="refund-success-001",
        )
        repeated = await refund_reservation(
            session, organization_id=identity_test_context["first_org"], reservation_id=successful.id,
            user_id=None, amount=20, idempotency_key="refund-success-001",
        )
        assert refunded.id == repeated.id
        await session.commit()
        account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == identity_test_context["first_org"]))
        assert account.balance == 1000


async def test_idempotency_conflict_is_rejected(identity_test_context) -> None:
    settings = Settings(_env_file=None)
    async with identity_test_context["session_factory"]() as session:
        await reserve_quota(
            session, settings, organization_id=identity_test_context["first_org"], user_id=None,
            operation_code="listing.generate", quantity=1, factors={}, idempotency_key="conflict-001",
        )
        try:
            await reserve_quota(
                session, settings, organization_id=identity_test_context["first_org"], user_id=None,
                operation_code="listing.generate", quantity=2, factors={}, idempotency_key="conflict-001",
            )
        except AppError as error:
            assert error.code == "quota.idempotency_conflict"
        else:
            raise AssertionError("idempotency conflict should have failed")


async def test_quota_api_is_tenant_scoped_and_adjustment_is_platform_only(identity_test_context) -> None:
    client = identity_test_context["client"]
    first = await auth_headers(client, "first-admin", "correct-password")
    second = await auth_headers(client, "second-admin", "second-password")
    assert (await client.get("/api/v1/quota/account", headers=first)).json()["balance"] == 1000
    assert (await client.get("/api/v1/quota/account", headers=second)).json()["balance"] == 50
    denied = await client.post("/api/v1/quota/adjustments", headers=first, json={
        "transaction_type": "adjust", "amount": 100, "idempotency_key": "manual:denied-001", "reason": "denied",
    })
    assert denied.status_code == 403

    platform = await auth_headers(client, "platform-admin", "platform-password")
    invalid = await client.post("/api/v1/quota/adjustments", headers=platform, json={
        "transaction_type": "grant", "amount": -100, "idempotency_key": "manual:invalid-001", "reason": "invalid",
    })
    assert invalid.status_code == 422
    adjusted = await client.post("/api/v1/quota/adjustments", headers=platform, json={
        "transaction_type": "adjust", "amount": 100, "idempotency_key": "manual:allowed-001", "reason": "support grant",
    })
    assert adjusted.status_code == 201, adjusted.text
    assert adjusted.json()["account"]["balance"] == 1100
    repeated = await client.post("/api/v1/quota/adjustments", headers=platform, json={
        "transaction_type": "adjust", "amount": 100, "idempotency_key": "manual:allowed-001", "reason": "support grant",
    })
    assert repeated.status_code == 201
    assert repeated.json()["account"]["balance"] == 1100

    first_transactions = await client.get("/api/v1/quota/transactions", headers=first)
    second_transactions = await client.get("/api/v1/quota/transactions", headers=second)
    assert first_transactions.json()["items"][0]["balance_after"] == 1100
    assert second_transactions.json()["items"][0]["balance_after"] == 50

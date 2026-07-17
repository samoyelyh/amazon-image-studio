import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.quota import (
    QuotaAccount,
    QuotaPackage,
    QuotaReservation,
    QuotaReservationStatus,
    QuotaRule,
    QuotaTransaction,
    QuotaTransactionType,
)
from app.schemas.quota import CostEstimateResponse, QuotaAccountResponse, QuotaReservationPage, QuotaReservationResponse, QuotaTransactionPage, QuotaTransactionResponse


UTC = timezone.utc
TERMINAL_RESERVATION_STATUSES = {
    QuotaReservationStatus.CONSUMED.value,
    QuotaReservationStatus.PARTIALLY_CONSUMED.value,
    QuotaReservationStatus.RELEASED.value,
    QuotaReservationStatus.REFUNDED.value,
    QuotaReservationStatus.PARTIALLY_REFUNDED.value,
    QuotaReservationStatus.EXPIRED.value,
}


@dataclass(frozen=True)
class CostEstimate:
    rule: QuotaRule
    quantity: int
    unit_cost: int
    total_cost: int
    multipliers: dict[str, str]


def account_response(account: QuotaAccount) -> QuotaAccountResponse:
    return QuotaAccountResponse(
        id=account.id,
        organization_id=account.organization_id,
        balance=account.balance,
        reserved_balance=account.reserved_balance,
        available_balance=account.balance - account.reserved_balance,
        version=account.version,
        updated_at=account.updated_at,
    )


async def get_account(session: AsyncSession, organization_id: str, *, lock: bool = False) -> QuotaAccount:
    statement = select(QuotaAccount).where(QuotaAccount.organization_id == organization_id)
    if lock:
        statement = statement.with_for_update()
    account = await session.scalar(statement)
    if account is None:
        raise AppError("quota.account_not_found", "Quota account has not been initialized", 409)
    return account


async def ensure_account(
    session: AsyncSession, organization_id: str, user_id: str | None, *, initial_balance: int = 0
) -> QuotaAccount:
    account = await session.scalar(select(QuotaAccount).where(QuotaAccount.organization_id == organization_id))
    if account is None:
        account = QuotaAccount(
            organization_id=organization_id,
            balance=initial_balance,
            reserved_balance=0,
            created_by=user_id,
            updated_by=user_id,
        )
        session.add(account)
        await session.flush()
        if initial_balance:
            _add_transaction(
                session, account=account, transaction_type=QuotaTransactionType.GRANT.value,
                amount=initial_balance, balance_delta=initial_balance, reserved_delta=0,
                idempotency_key=f"bootstrap:{organization_id}", user_id=user_id,
                metadata={"reason": "bootstrap quota"},
            )
    return account


async def active_rule(
    session: AsyncSession, organization_id: str, operation_code: str, *, now: datetime | None = None
) -> QuotaRule:
    now = now or datetime.now(UTC)
    common = [
        QuotaRule.operation_code == operation_code,
        QuotaRule.enabled.is_(True),
        QuotaRule.effective_from <= now,
        or_(QuotaRule.effective_to.is_(None), QuotaRule.effective_to > now),
    ]
    rule = await session.scalar(
        select(QuotaRule).where(*common, QuotaRule.organization_id == organization_id)
        .order_by(QuotaRule.effective_from.desc()).limit(1)
    )
    if rule is None:
        rule = await session.scalar(
            select(QuotaRule).where(*common, QuotaRule.organization_id.is_(None))
            .order_by(QuotaRule.effective_from.desc()).limit(1)
        )
    if rule is None:
        raise AppError("quota.rule_not_found", "No active billing rule exists for this operation", 422, {"operation_code": operation_code})
    return rule


def _multiplier(values: dict[str, object], selected: str | None, dimension: str) -> Decimal:
    if selected is None:
        return Decimal("1")
    raw = values.get(selected, 1)
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as error:
        raise AppError("quota.invalid_rule", "Billing rule contains an invalid multiplier", 500, {"dimension": dimension}) from error
    if value < 0:
        raise AppError("quota.invalid_rule", "Billing rule contains a negative multiplier", 500, {"dimension": dimension})
    return value


async def estimate_cost(
    session: AsyncSession,
    *,
    organization_id: str,
    operation_code: str,
    quantity: int,
    factors: dict[str, str] | None = None,
) -> CostEstimate:
    if quantity < 1 or quantity > 10000:
        raise AppError("quota.invalid_quantity", "Quantity must be between 1 and 10000", 422)
    factors = factors or {}
    rule = await active_rule(session, organization_id, operation_code)
    dimensions = {
        "model": _multiplier(rule.model_multipliers, factors.get("model"), "model"),
        "quality": _multiplier(rule.quality_multipliers, factors.get("quality"), "quality"),
        "resolution": _multiplier(rule.resolution_multipliers, factors.get("resolution"), "resolution"),
        "resource_pool": _multiplier(rule.resource_pool_multipliers, factors.get("resource_pool"), "resource_pool"),
    }
    unit = Decimal(rule.base_cost)
    for multiplier in dimensions.values():
        unit *= multiplier
    unit_cost = int(unit.to_integral_value(rounding=ROUND_CEILING))
    return CostEstimate(rule, quantity, unit_cost, unit_cost * quantity, {key: str(value) for key, value in dimensions.items()})


async def estimate_response(
    session: AsyncSession, *, organization_id: str, operation_code: str, quantity: int, factors: dict[str, str]
) -> CostEstimateResponse:
    estimate = await estimate_cost(
        session, organization_id=organization_id, operation_code=operation_code, quantity=quantity, factors=factors
    )
    account = await get_account(session, organization_id)
    available = account.balance - account.reserved_balance
    return CostEstimateResponse(
        operation_code=operation_code,
        rule_id=estimate.rule.id,
        quantity=quantity,
        base_cost=estimate.rule.base_cost,
        unit_cost=estimate.unit_cost,
        estimated_cost=estimate.total_cost,
        multipliers=estimate.multipliers,
        available_balance=available,
        sufficient=available >= estimate.total_cost,
    )


def _add_transaction(
    session: AsyncSession,
    *,
    account: QuotaAccount,
    transaction_type: str,
    amount: int,
    balance_delta: int,
    reserved_delta: int,
    idempotency_key: str,
    user_id: str | None,
    reservation: QuotaReservation | None = None,
    operation_code: str | None = None,
    reference_type: str | None = None,
    reference_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> QuotaTransaction:
    transaction = QuotaTransaction(
        organization_id=account.organization_id,
        account_id=account.id,
        reservation_id=reservation.id if reservation else None,
        transaction_type=transaction_type,
        amount=amount,
        balance_delta=balance_delta,
        reserved_delta=reserved_delta,
        balance_after=account.balance,
        reserved_after=account.reserved_balance,
        operation_code=operation_code,
        idempotency_key=idempotency_key,
        reference_type=reference_type,
        reference_id=reference_id,
        metadata_json=metadata,
        created_by=user_id,
        created_at=datetime.now(UTC),
    )
    session.add(transaction)
    return transaction


async def adjust_balance(
    session: AsyncSession,
    *,
    organization_id: str,
    user_id: str,
    transaction_type: str,
    amount: int,
    idempotency_key: str,
    reason: str,
) -> tuple[QuotaAccount, QuotaTransaction]:
    account = await get_account(session, organization_id, lock=True)
    existing = await session.scalar(select(QuotaTransaction).where(
        QuotaTransaction.organization_id == organization_id,
        QuotaTransaction.idempotency_key == idempotency_key,
    ).with_for_update())
    if existing:
        expected_delta = amount if transaction_type == QuotaTransactionType.ADJUST.value else (
            -abs(amount) if transaction_type == QuotaTransactionType.EXPIRE.value else abs(amount)
        )
        if existing.transaction_type != transaction_type or existing.balance_delta != expected_delta:
            raise AppError("quota.idempotency_conflict", "Idempotency key was already used for another quota operation", 409)
        return account, existing
    if transaction_type in {QuotaTransactionType.GRANT.value, QuotaTransactionType.RECHARGE.value}:
        delta = abs(amount)
    elif transaction_type == QuotaTransactionType.EXPIRE.value:
        delta = -abs(amount)
    elif transaction_type == QuotaTransactionType.ADJUST.value:
        delta = amount
    else:
        raise AppError("quota.invalid_adjustment_type", "Unsupported quota adjustment type", 422)
    if account.balance + delta < account.reserved_balance:
        raise AppError("quota.adjustment_below_reserved", "Adjustment would reduce balance below frozen quota", 409)
    account.balance += delta
    account.version += 1
    account.updated_by = user_id
    transaction = _add_transaction(
        session, account=account, transaction_type=transaction_type, amount=abs(amount),
        balance_delta=delta, reserved_delta=0, idempotency_key=idempotency_key,
        user_id=user_id, metadata={"reason": reason},
    )
    await session.flush()
    return account, transaction


def _request_hash(operation_code: str, quantity: int, factors: dict[str, str], reference_type: str | None, reference_id: str | None) -> str:
    value = json.dumps({
        "operation_code": operation_code, "quantity": quantity, "factors": factors,
        "reference_type": reference_type, "reference_id": reference_id,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(value.encode("utf-8")).hexdigest()


async def reserve_quota(
    session: AsyncSession,
    settings: Settings,
    *,
    organization_id: str,
    user_id: str,
    operation_code: str,
    quantity: int,
    factors: dict[str, str],
    idempotency_key: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> QuotaReservation:
    estimate = await estimate_cost(
        session, organization_id=organization_id, operation_code=operation_code, quantity=quantity, factors=factors
    )
    fingerprint = _request_hash(operation_code, quantity, factors, reference_type, reference_id)
    account = await get_account(session, organization_id, lock=True)
    existing = await session.scalar(select(QuotaReservation).where(
        QuotaReservation.organization_id == organization_id,
        QuotaReservation.idempotency_key == idempotency_key,
    ).with_for_update())
    if existing:
        if existing.request_hash != fingerprint:
            raise AppError("quota.idempotency_conflict", "Idempotency key was already used with different reservation input", 409)
        return existing
    available = account.balance - account.reserved_balance
    if available < estimate.total_cost:
        raise AppError("quota.insufficient", "Available quota is insufficient", 402, {
            "required": estimate.total_cost, "available": available,
        })
    now = datetime.now(UTC)
    reservation = QuotaReservation(
        organization_id=organization_id,
        account_id=account.id,
        rule_id=estimate.rule.id,
        operation_code=operation_code,
        idempotency_key=idempotency_key,
        request_hash=fingerprint,
        quantity=quantity,
        unit_cost=estimate.unit_cost,
        reserved_amount=estimate.total_cost,
        factors_json=factors,
        reference_type=reference_type,
        reference_id=reference_id,
        expires_at=now + timedelta(minutes=settings.quota_reservation_ttl_minutes),
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(reservation)
    await session.flush()
    account.reserved_balance += estimate.total_cost
    account.version += 1
    account.updated_by = user_id
    _add_transaction(
        session, account=account, reservation=reservation, transaction_type=QuotaTransactionType.RESERVE.value,
        amount=estimate.total_cost, balance_delta=0, reserved_delta=estimate.total_cost,
        idempotency_key=f"reserve:{idempotency_key}", user_id=user_id, operation_code=operation_code,
        reference_type=reference_type, reference_id=reference_id,
        metadata={"quantity": quantity, "unit_cost": estimate.unit_cost, "multipliers": estimate.multipliers},
    )
    await session.flush()
    return reservation


async def _locked_reservation(
    session: AsyncSession, organization_id: str, reservation_id: str
) -> tuple[QuotaAccount, QuotaReservation]:
    account = await get_account(session, organization_id, lock=True)
    reservation = await session.scalar(select(QuotaReservation).where(
        QuotaReservation.id == reservation_id,
        QuotaReservation.organization_id == organization_id,
    ).with_for_update())
    if reservation is None:
        raise AppError("quota.reservation_not_found", "Quota reservation was not found", 404)
    return account, reservation


async def settle_reservation(
    session: AsyncSession,
    *,
    organization_id: str,
    reservation_id: str,
    user_id: str,
    actual_quantity: int,
    idempotency_key: str,
) -> QuotaReservation:
    account, reservation = await _locked_reservation(session, organization_id, reservation_id)
    if reservation.status in TERMINAL_RESERVATION_STATUSES:
        if reservation.settlement_idempotency_key == idempotency_key and reservation.actual_quantity == actual_quantity:
            return reservation
        raise AppError("quota.reservation_already_settled", "Quota reservation has already been settled", 409)
    if actual_quantity < 0 or actual_quantity > reservation.quantity:
        raise AppError("quota.invalid_actual_quantity", "Actual quantity exceeds the reservation", 422)
    consume = reservation.unit_cost * actual_quantity
    release = reservation.reserved_amount - consume
    if consume:
        account.balance -= consume
        account.reserved_balance -= consume
        _add_transaction(
            session, account=account, reservation=reservation, transaction_type=QuotaTransactionType.CONSUME.value,
            amount=consume, balance_delta=-consume, reserved_delta=-consume,
            idempotency_key=f"consume:{idempotency_key}", user_id=user_id,
            operation_code=reservation.operation_code, reference_type=reservation.reference_type,
            reference_id=reservation.reference_id, metadata={"actual_quantity": actual_quantity},
        )
    if release:
        account.reserved_balance -= release
        _add_transaction(
            session, account=account, reservation=reservation, transaction_type=QuotaTransactionType.RELEASE.value,
            amount=release, balance_delta=0, reserved_delta=-release,
            idempotency_key=f"release:{idempotency_key}", user_id=user_id,
            operation_code=reservation.operation_code, reference_type=reservation.reference_type,
            reference_id=reservation.reference_id, metadata={"reason": "partial settlement"},
        )
    reservation.actual_quantity = actual_quantity
    reservation.consumed_amount = consume
    reservation.released_amount = release
    reservation.status = (
        QuotaReservationStatus.RELEASED.value if actual_quantity == 0 else
        QuotaReservationStatus.CONSUMED.value if actual_quantity == reservation.quantity else
        QuotaReservationStatus.PARTIALLY_CONSUMED.value
    )
    reservation.settlement_idempotency_key = idempotency_key
    reservation.settled_at = datetime.now(UTC)
    reservation.updated_by = user_id
    account.version += 1
    account.updated_by = user_id
    await session.flush()
    return reservation


async def release_reservation(
    session: AsyncSession,
    *,
    organization_id: str,
    reservation_id: str,
    user_id: str,
    idempotency_key: str,
    expired: bool = False,
) -> QuotaReservation:
    account, reservation = await _locked_reservation(session, organization_id, reservation_id)
    if reservation.status in TERMINAL_RESERVATION_STATUSES:
        if reservation.settlement_idempotency_key == idempotency_key:
            return reservation
        raise AppError("quota.reservation_already_settled", "Quota reservation has already been settled", 409)
    account.reserved_balance -= reservation.reserved_amount
    account.version += 1
    account.updated_by = user_id
    transaction_type = QuotaTransactionType.EXPIRE.value if expired else QuotaTransactionType.RELEASE.value
    _add_transaction(
        session, account=account, reservation=reservation, transaction_type=transaction_type,
        amount=reservation.reserved_amount, balance_delta=0, reserved_delta=-reservation.reserved_amount,
        idempotency_key=f"{transaction_type}:{idempotency_key}", user_id=user_id,
        operation_code=reservation.operation_code, reference_type=reservation.reference_type,
        reference_id=reservation.reference_id, metadata={"reason": "expired" if expired else "failed or cancelled"},
    )
    reservation.actual_quantity = 0
    reservation.released_amount = reservation.reserved_amount
    reservation.status = QuotaReservationStatus.EXPIRED.value if expired else QuotaReservationStatus.RELEASED.value
    reservation.settlement_idempotency_key = idempotency_key
    reservation.settled_at = datetime.now(UTC)
    reservation.updated_by = user_id
    await session.flush()
    return reservation


async def refund_reservation(
    session: AsyncSession,
    *,
    organization_id: str,
    reservation_id: str,
    user_id: str,
    amount: int,
    idempotency_key: str,
) -> QuotaReservation:
    account, reservation = await _locked_reservation(session, organization_id, reservation_id)
    existing = await session.scalar(select(QuotaTransaction).where(
        QuotaTransaction.organization_id == organization_id,
        QuotaTransaction.idempotency_key == f"refund:{idempotency_key}",
    ).with_for_update())
    if existing:
        if existing.amount != amount or existing.reservation_id != reservation_id:
            raise AppError("quota.idempotency_conflict", "Refund idempotency key was reused with different input", 409)
        return reservation
    refundable = reservation.consumed_amount - reservation.refunded_amount
    if amount < 1 or amount > refundable:
        raise AppError("quota.invalid_refund", "Refund exceeds the consumed quota remaining", 422, {"refundable": refundable})
    account.balance += amount
    account.version += 1
    account.updated_by = user_id
    reservation.refunded_amount += amount
    reservation.status = (
        QuotaReservationStatus.REFUNDED.value
        if reservation.refunded_amount == reservation.consumed_amount
        else QuotaReservationStatus.PARTIALLY_REFUNDED.value
    )
    reservation.updated_by = user_id
    _add_transaction(
        session, account=account, reservation=reservation, transaction_type=QuotaTransactionType.REFUND.value,
        amount=amount, balance_delta=amount, reserved_delta=0,
        idempotency_key=f"refund:{idempotency_key}", user_id=user_id,
        operation_code=reservation.operation_code, reference_type=reservation.reference_type,
        reference_id=reservation.reference_id,
    )
    await session.flush()
    return reservation


async def list_transactions(
    session: AsyncSession, organization_id: str, limit: int, offset: int
) -> QuotaTransactionPage:
    total = int(await session.scalar(select(func.count()).select_from(QuotaTransaction).where(
        QuotaTransaction.organization_id == organization_id
    )) or 0)
    items = list((await session.scalars(select(QuotaTransaction).where(
        QuotaTransaction.organization_id == organization_id
    ).order_by(QuotaTransaction.created_at.desc()).limit(limit).offset(offset))).all())
    return QuotaTransactionPage(
        items=[QuotaTransactionResponse.model_validate(item) for item in items], total=total, limit=limit, offset=offset
    )


async def list_reservations(
    session: AsyncSession, organization_id: str, limit: int, offset: int
) -> QuotaReservationPage:
    total = int(await session.scalar(select(func.count()).select_from(QuotaReservation).where(
        QuotaReservation.organization_id == organization_id
    )) or 0)
    items = list((await session.scalars(select(QuotaReservation).where(
        QuotaReservation.organization_id == organization_id
    ).order_by(QuotaReservation.created_at.desc()).limit(limit).offset(offset))).all())
    return QuotaReservationPage(
        items=[QuotaReservationResponse.model_validate(item) for item in items], total=total, limit=limit, offset=offset
    )


async def list_active_rules(session: AsyncSession, organization_id: str) -> list[QuotaRule]:
    now = datetime.now(UTC)
    rules = list((await session.scalars(select(QuotaRule).where(
        QuotaRule.enabled.is_(True), QuotaRule.effective_from <= now,
        or_(QuotaRule.effective_to.is_(None), QuotaRule.effective_to > now),
        or_(QuotaRule.organization_id == organization_id, QuotaRule.organization_id.is_(None)),
    ).order_by(QuotaRule.operation_code, QuotaRule.organization_id.desc(), QuotaRule.effective_from.desc()))).all())
    selected: dict[str, QuotaRule] = {}
    for rule in rules:
        if rule.operation_code not in selected or (selected[rule.operation_code].organization_id is None and rule.organization_id is not None):
            selected[rule.operation_code] = rule
    return list(selected.values())


async def list_packages(session: AsyncSession) -> list[QuotaPackage]:
    return list((await session.scalars(select(QuotaPackage).where(QuotaPackage.enabled.is_(True)).order_by(QuotaPackage.quota_amount))).all())

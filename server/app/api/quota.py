from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.session import get_db_session
from app.schemas.quota import (
    CostEstimateRequest,
    CostEstimateResponse,
    QuotaAccountResponse,
    QuotaAdjustmentRequest,
    QuotaAdjustmentResponse,
    QuotaPackageResponse,
    QuotaReservationPage,
    QuotaRuleResponse,
    QuotaTransactionPage,
    QuotaTransactionResponse,
)
from app.security.principal import Principal, require_permissions
from app.services.audit_service import add_audit_log
from app.services.billing_service import (
    account_response,
    adjust_balance,
    estimate_response,
    get_account,
    list_active_rules,
    list_packages,
    list_reservations,
    list_transactions,
)


router = APIRouter(prefix="/quota", tags=["quota"])


def organization_id(principal: Principal) -> str:
    if principal.organization is None:
        raise AppError("organization.required", "Select an organization first", 409)
    return principal.organization.id


@router.get("/account", response_model=QuotaAccountResponse)
async def quota_account(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("quota.read")),
) -> QuotaAccountResponse:
    return account_response(await get_account(session, organization_id(principal)))


@router.get("/transactions", response_model=QuotaTransactionPage)
async def quota_transactions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("quota.read")),
) -> QuotaTransactionPage:
    return await list_transactions(session, organization_id(principal), limit, offset)


@router.get("/reservations", response_model=QuotaReservationPage)
async def quota_reservations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("quota.read")),
) -> QuotaReservationPage:
    return await list_reservations(session, organization_id(principal), limit, offset)


@router.get("/rules", response_model=list[QuotaRuleResponse])
async def quota_rules(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("quota.estimate")),
) -> list[QuotaRuleResponse]:
    return [QuotaRuleResponse.model_validate(item) for item in await list_active_rules(session, organization_id(principal))]


@router.get("/packages", response_model=list[QuotaPackageResponse])
async def quota_packages(
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("quota.read")),
) -> list[QuotaPackageResponse]:
    return [QuotaPackageResponse.model_validate(item) for item in await list_packages(session)]


@router.post("/estimate", response_model=CostEstimateResponse)
async def estimate_quota(
    payload: CostEstimateRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("quota.estimate")),
) -> CostEstimateResponse:
    return await estimate_response(
        session,
        organization_id=organization_id(principal),
        operation_code=payload.operation_code,
        quantity=payload.quantity,
        factors=payload.factors(),
    )


@router.post("/adjustments", response_model=QuotaAdjustmentResponse, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    payload: QuotaAdjustmentRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: Principal = Depends(require_permissions("quota.manage")),
) -> QuotaAdjustmentResponse:
    org_id = organization_id(principal)
    account, transaction = await adjust_balance(
        session,
        organization_id=org_id,
        user_id=principal.user.id,
        transaction_type=payload.transaction_type,
        amount=payload.amount,
        idempotency_key=payload.idempotency_key,
        reason=payload.reason,
    )
    add_audit_log(
        session,
        request=request,
        actor_user_id=principal.user.id,
        organization_id=org_id,
        action="quota.adjustment",
        resource_type="quota_account",
        resource_id=account.id,
        metadata={
            "transaction_id": transaction.id,
            "transaction_type": transaction.transaction_type,
            "amount": transaction.amount,
            "idempotency_key": payload.idempotency_key,
        },
    )
    await session.commit()
    await session.refresh(account)
    await session.refresh(transaction)
    return QuotaAdjustmentResponse(
        account=account_response(account), transaction=QuotaTransactionResponse.model_validate(transaction)
    )

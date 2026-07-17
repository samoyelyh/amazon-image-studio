from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QuotaAccountResponse(BaseModel):
    id: str
    organization_id: str
    balance: int
    reserved_balance: int
    available_balance: int
    version: int
    updated_at: datetime


class CostEstimateRequest(BaseModel):
    operation_code: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=120)
    quantity: int = Field(ge=1, le=10000)
    model: str | None = Field(default=None, max_length=120)
    quality: str | None = Field(default=None, max_length=80)
    resolution: str | None = Field(default=None, max_length=80)
    resource_pool: str | None = Field(default=None, max_length=80)

    def factors(self) -> dict[str, str]:
        return {
            key: value for key, value in {
                "model": self.model,
                "quality": self.quality,
                "resolution": self.resolution,
                "resource_pool": self.resource_pool,
            }.items() if value is not None
        }


class CostEstimateResponse(BaseModel):
    operation_code: str
    rule_id: str
    quantity: int
    base_cost: int
    unit_cost: int
    estimated_cost: int
    multipliers: dict[str, str]
    available_balance: int
    sufficient: bool


class QuotaRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str | None
    operation_code: str
    name: str
    base_cost: int
    model_multipliers: dict[str, object]
    quality_multipliers: dict[str, object]
    resolution_multipliers: dict[str, object]
    resource_pool_multipliers: dict[str, object]
    effective_from: datetime
    effective_to: datetime | None


class QuotaPackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    quota_amount: int
    price: Decimal
    currency: str
    valid_days: int | None


class QuotaTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reservation_id: str | None
    transaction_type: str
    amount: int
    balance_delta: int
    reserved_delta: int
    balance_after: int
    reserved_after: int
    operation_code: str | None
    reference_type: str | None
    reference_id: str | None
    metadata_json: dict[str, object] | None
    created_by: str | None
    created_at: datetime


class QuotaTransactionPage(BaseModel):
    items: list[QuotaTransactionResponse]
    total: int
    limit: int
    offset: int


class QuotaReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    operation_code: str
    quantity: int
    actual_quantity: int | None
    unit_cost: int
    reserved_amount: int
    consumed_amount: int
    released_amount: int
    refunded_amount: int
    status: str
    factors_json: dict[str, object]
    reference_type: str | None
    reference_id: str | None
    expires_at: datetime
    settled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class QuotaReservationPage(BaseModel):
    items: list[QuotaReservationResponse]
    total: int
    limit: int
    offset: int


class QuotaAdjustmentRequest(BaseModel):
    transaction_type: Literal["grant", "recharge", "adjust", "expire"]
    amount: int = Field(ge=-1_000_000_000, le=1_000_000_000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", min_length=8, max_length=160)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("amount")
    @classmethod
    def amount_cannot_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("amount cannot be zero")
        return value

    @field_validator("reason")
    @classmethod
    def reason_cannot_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_amount_direction(self) -> "QuotaAdjustmentRequest":
        if self.transaction_type != "adjust" and self.amount < 0:
            raise ValueError("grant, recharge, and expire amounts must be positive")
        return self


class QuotaAdjustmentResponse(BaseModel):
    account: QuotaAccountResponse
    transaction: QuotaTransactionResponse

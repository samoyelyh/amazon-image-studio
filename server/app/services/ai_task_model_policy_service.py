from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.services.category_listing_service import resolve_bound_model_code


@dataclass(frozen=True)
class AITaskRoute:
    task_type: str
    operation_code: str
    capability: str
    model_code: str
    used_fallback_binding: bool = False


@dataclass(frozen=True)
class AnalysisRetryDecision:
    attempt: int
    use_fallback: bool


def next_analysis_retry(*, attempt: int, fallback_used: bool) -> AnalysisRetryDecision | None:
    """Mini may run twice total, followed by at most one Luna fallback."""
    if fallback_used:
        return None
    if attempt == 1:
        return AnalysisRetryDecision(attempt=2, use_fallback=False)
    if attempt == 2:
        return AnalysisRetryDecision(attempt=3, use_fallback=True)
    return None


TASK_OPERATION_CODES = {
    "REFERENCE_ANALYSIS": "listing.reference_analyze",
    "REFERENCE_LIBRARY_ANALYSIS": "listing.reference_library_analyze",
    "PRODUCT_IDENTITY_EXTRACTION": "listing.product_identity_extract",
    "MODEL_REFERENCE_ANALYSIS": "listing.model_reference_analyze",
    "FULL_VISUAL_PLANNING": "listing.plan",
    "MODULE_PLANNING": "listing.plan",
    "PROMPT_OPTIMIZATION": "listing.plan",
    "CREATIVE_PLANNING": "listing.plan",
    "IMAGE_GENERATION": "listing.generate",
}


async def resolve_ai_task_route(
    db: AsyncSession, *, organization_id: str, task_type: str, capability: str,
) -> AITaskRoute:
    operation_code = TASK_OPERATION_CODES[task_type]
    try:
        model_code = await resolve_bound_model_code(
            db, organization_id=organization_id, operation_code=operation_code, capability=capability,
        )
        return AITaskRoute(task_type, operation_code, capability, model_code)
    except AppError:
        # Upgrade compatibility: deployments can migrate first and bind the dedicated
        # lightweight model afterwards without breaking existing projects.
        fallback_operation = "listing.plan" if capability == "text_generation" else "listing.generate"
        model_code = await resolve_bound_model_code(
            db, organization_id=organization_id, operation_code=fallback_operation, capability=capability,
        )
        return AITaskRoute(task_type, fallback_operation, capability, model_code, True)

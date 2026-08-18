import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli.bootstrap_identity import slugify
from app.core.config import get_settings
from app.db.session import get_engine
from app.models.identity import Organization
from app.models.quota import QuotaPackage, QuotaRule
from app.services.billing_service import ensure_account


UTC = timezone.utc
DEFAULT_RULES = {
    "listing.plan": ("Listing AI 策划", 10),
    "listing.generate": ("Listing 图片生成", 10),
    "batch_tryon.generate": ("批量套图生成", 10),
    "batch_tryon.style_analyze": ("批量套图款式分析", 1),
    "batch_tryon.prompt_analyze": ("批量套图提示词分析", 1),
    "batch_tryon.prompt_analyze_detailed": ("批量套图逐图精细提示词分析", 1),
    "batch_tryon.region_replace": ("批量套图区域涂抹替换", 10),
    "print_design.replace": ("印花局部替换", 10),
    "print_design.blend": ("印花边缘融合", 10),
    "aplus.plan": ("A+ AI 策划", 10),
    "aplus.generate": ("A+ 模块生成", 10),
    "asset.extract": ("素材提取", 10),
}
DEFAULT_PACKAGES = (
    ("starter-1000", "入门额度包", 1000, Decimal("99.00")),
    ("team-5000", "团队额度包", 5000, Decimal("399.00")),
)


async def bootstrap(session: AsyncSession) -> None:
    settings = get_settings()
    effective_from = datetime(2020, 1, 1, tzinfo=UTC)
    for operation_code, (name, base_cost) in DEFAULT_RULES.items():
        rule = await session.scalar(select(QuotaRule).where(
            QuotaRule.organization_id.is_(None),
            QuotaRule.operation_code == operation_code,
            QuotaRule.effective_from == effective_from,
        ))
        if rule is None:
            session.add(QuotaRule(
                organization_id=None,
                operation_code=operation_code,
                name=name,
                base_cost=base_cost,
                model_multipliers={},
                quality_multipliers={"standard": "1", "high": "1.5"},
                resolution_multipliers={"1024": "1", "2048": "2"},
                resource_pool_multipliers={"platform": "1", "personal": "0"},
                effective_from=effective_from,
            ))
    for code, name, quota_amount, price in DEFAULT_PACKAGES:
        package = await session.scalar(select(QuotaPackage).where(QuotaPackage.code == code))
        if package is None:
            session.add(QuotaPackage(code=code, name=name, quota_amount=quota_amount, price=price))
    await session.flush()

    organizations = list((await session.scalars(select(Organization))).all())
    bootstrap_slug = slugify(settings.bootstrap_organization_name)
    for organization in organizations:
        initial_balance = settings.bootstrap_quota_balance if organization.slug == bootstrap_slug else 0
        await ensure_account(session, organization.id, organization.created_by, initial_balance=initial_balance)
    await session.commit()
    print(f"Billing bootstrap ready with {len(DEFAULT_RULES)} rules and {len(organizations)} quota accounts.")


async def main() -> None:
    session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        await bootstrap(session)


if __name__ == "__main__":
    asyncio.run(main())

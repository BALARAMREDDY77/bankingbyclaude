"""Bank Repository — data access for Bank model."""

from typing import List, Optional
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.bank import Bank, BankStatus, BankTier
from app.db.repositories.base import BaseRepository


class BankRepository(BaseRepository[Bank]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Bank, session)

    async def get_active(self, offset: int = 0, limit: int = 100) -> List[Bank]:
        result = await self.session.execute(
            select(Bank)
            .where(and_(Bank.status == BankStatus.ACTIVE, Bank.deleted_at.is_(None)))
            .offset(offset).limit(limit)
            .order_by(Bank.name)
        )
        return list(result.scalars().all())

    async def get_by_short_code(self, short_code: str) -> Optional[Bank]:
        result = await self.session.execute(
            select(Bank).where(
                and_(Bank.short_code == short_code.upper(), Bank.deleted_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def get_partners(self) -> List[Bank]:
        result = await self.session.execute(
            select(Bank).where(
                and_(
                    Bank.is_partner.is_(True),
                    Bank.status == BankStatus.ACTIVE,
                    Bank.deleted_at.is_(None),
                )
            ).order_by(Bank.tier, Bank.name)
        )
        return list(result.scalars().all())

    async def get_by_tier(self, tier: BankTier) -> List[Bank]:
        result = await self.session.execute(
            select(Bank).where(
                and_(Bank.tier == tier, Bank.deleted_at.is_(None))
            ).order_by(Bank.name)
        )
        return list(result.scalars().all())

    async def short_code_exists(self, short_code: str) -> bool:
        result = await self.session.execute(
            select(Bank.id).where(Bank.short_code == short_code.upper())
        )
        return result.scalar_one_or_none() is not None

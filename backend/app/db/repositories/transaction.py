"""Transaction Repository — immutable financial record access."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.transaction import Transaction, TransactionStatus, TransactionType
from app.db.repositories.base import BaseRepository


class TransactionRepository(BaseRepository[Transaction]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Transaction, session)

    async def get_by_reference(self, reference: str) -> Optional[Transaction]:
        result = await self.session.execute(
            select(Transaction).where(Transaction.reference_number == reference)
        )
        return result.scalar_one_or_none()

    async def get_for_user(
        self,
        user_id: uuid.UUID,
        transaction_type: Optional[TransactionType] = None,
        status: Optional[TransactionStatus] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> List[Transaction]:
        q = select(Transaction).where(Transaction.user_id == user_id)
        if transaction_type:
            q = q.where(Transaction.transaction_type == transaction_type)
        if status:
            q = q.where(Transaction.status == status)
        if from_date:
            q = q.where(Transaction.created_at >= from_date)
        if to_date:
            q = q.where(Transaction.created_at <= to_date)
        q = q.order_by(Transaction.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_flagged(self, limit: int = 100) -> List[Transaction]:
        result = await self.session.execute(
            select(Transaction)
            .where(Transaction.is_flagged.is_(True))
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_user_total(
        self,
        user_id: uuid.UUID,
        transaction_type: Optional[TransactionType] = None,
    ) -> Decimal:
        q = (
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.status == TransactionStatus.COMPLETED,
                )
            )
        )
        if transaction_type:
            q = q.where(Transaction.transaction_type == transaction_type)
        result = await self.session.execute(q)
        return result.scalar_one()

    async def reference_exists(self, reference: str) -> bool:
        result = await self.session.execute(
            select(Transaction.id).where(Transaction.reference_number == reference)
        )
        return result.scalar_one_or_none() is not None

    async def generate_reference(self) -> str:
        """Generate unique transaction reference: TXN-YYYYMMDDHHMMSS-NNNNNN."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d%H%M%S")
        result = await self.session.execute(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.reference_number.like(f"TXN-{ts[:8]}%"))
        )
        seq = (result.scalar_one() or 0) + 1
        return f"TXN-{ts}-{seq:06d}"

    async def volume_by_type(self, user_id: Optional[uuid.UUID] = None) -> dict:
        q = (
            select(
                Transaction.transaction_type,
                func.count().label("count"),
                func.sum(Transaction.amount).label("total"),
            )
            .where(Transaction.status == TransactionStatus.COMPLETED)
            .group_by(Transaction.transaction_type)
        )
        if user_id:
            q = q.where(Transaction.user_id == user_id)
        result = await self.session.execute(q)
        return {
            row.transaction_type.value: {
                "count": row.count,
                "total": float(row.total or 0),
            }
            for row in result.all()
        }

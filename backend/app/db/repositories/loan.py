"""Loan Application Repository — full lifecycle data access."""

import uuid
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.loan import LoanApplication, LoanStatus, LoanType
from app.db.repositories.base import BaseRepository


class LoanRepository(BaseRepository[LoanApplication]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(LoanApplication, session)

    async def get_by_application_number(self, number: str) -> Optional[LoanApplication]:
        result = await self.session.execute(
            select(LoanApplication).where(
                and_(
                    LoanApplication.application_number == number,
                    LoanApplication.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_for_user(
        self,
        user_id: uuid.UUID,
        status: Optional[LoanStatus] = None,
        loan_type: Optional[LoanType] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> List[LoanApplication]:
        q = select(LoanApplication).where(
            and_(
                LoanApplication.user_id == user_id,
                LoanApplication.deleted_at.is_(None),
            )
        )
        if status:
            q = q.where(LoanApplication.status == status)
        if loan_type:
            q = q.where(LoanApplication.loan_type == loan_type)
        q = q.order_by(LoanApplication.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_with_documents(self, loan_id: uuid.UUID) -> Optional[LoanApplication]:
        result = await self.session.execute(
            select(LoanApplication)
            .options(selectinload(LoanApplication.documents))
            .where(
                and_(
                    LoanApplication.id == loan_id,
                    LoanApplication.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_ai_assessment(self, limit: int = 20) -> List[LoanApplication]:
        result = await self.session.execute(
            select(LoanApplication)
            .where(
                and_(
                    LoanApplication.status == LoanStatus.AI_ASSESSMENT,
                    LoanApplication.deleted_at.is_(None),
                )
            )
            .order_by(LoanApplication.is_priority.desc(), LoanApplication.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        loan_id: uuid.UUID,
        status: LoanStatus,
        updated_by: Optional[uuid.UUID] = None,
        reason: Optional[str] = None,
    ) -> None:
        values = {"status": status, "updated_by": updated_by}
        if reason:
            values["decision_reason"] = reason
        await self.session.execute(
            update(LoanApplication)
            .where(LoanApplication.id == loan_id)
            .values(**values)
        )
        await self.session.flush()

    async def update_ai_assessment(
        self,
        loan_id: uuid.UUID,
        risk_score: Decimal,
        recommendation: str,
        confidence: Decimal,
    ) -> None:
        from datetime import datetime, timezone
        await self.session.execute(
            update(LoanApplication)
            .where(LoanApplication.id == loan_id)
            .values(
                ai_risk_score=risk_score,
                ai_recommendation=recommendation,
                ai_confidence=confidence,
                ai_assessed_at=datetime.now(timezone.utc).isoformat(),
                status=LoanStatus.CREDIT_CHECK,
            )
        )
        await self.session.flush()

    async def count_by_status(self, bank_id: Optional[uuid.UUID] = None) -> dict:
        q = (
            select(LoanApplication.status, func.count().label("count"))
            .where(LoanApplication.deleted_at.is_(None))
            .group_by(LoanApplication.status)
        )
        if bank_id:
            q = q.where(LoanApplication.bank_id == bank_id)
        result = await self.session.execute(q)
        return {row.status.value: row.count for row in result.all()}

    async def get_overdue(self, limit: int = 100) -> List[LoanApplication]:
        result = await self.session.execute(
            select(LoanApplication)
            .where(
                and_(
                    LoanApplication.status == LoanStatus.ACTIVE,
                    LoanApplication.overdue_days > 0,
                    LoanApplication.deleted_at.is_(None),
                )
            )
            .order_by(LoanApplication.overdue_days.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def generate_application_number(self) -> str:
        """Generate unique application number: LOAN-YYYYMMDD-NNNNN."""
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        result = await self.session.execute(
            select(func.count())
            .select_from(LoanApplication)
            .where(LoanApplication.application_number.like(f"LOAN-{today}-%"))
        )
        seq = (result.scalar_one() or 0) + 1
        return f"LOAN-{today}-{seq:05d}"

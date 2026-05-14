"""
Base Repository Pattern
========================
Provides a generic async CRUD repository.
All domain repositories extend BaseRepository[ModelType].
This enforces the repository pattern and keeps business logic
out of controllers and out of models.

Usage:
    class AccountRepository(BaseRepository[Account]):
        async def find_by_iban(self, iban: str) -> Optional[Account]:
            result = await self.session.execute(
                select(Account).where(Account.iban == iban)
            )
            return result.scalar_one_or_none()
"""

from typing import Any, Dict, Generic, List, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic async repository providing standard CRUD operations.
    All operations are async-first and use the injected session.
    """

    def __init__(self, model: Type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get_by_id(self, record_id: UUID) -> Optional[ModelType]:
        """Fetch a single record by primary key."""
        result = await self.session.execute(
            select(self.model).where(self.model.id == record_id)  # type: ignore
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> List[ModelType]:
        """Fetch paginated list of all records."""
        result = await self.session.execute(
            select(self.model).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        """Return total count of records in table."""
        result = await self.session.execute(
            select(func.count()).select_from(self.model)
        )
        return result.scalar_one()

    async def create(self, data: Dict[str, Any]) -> ModelType:
        """Create and persist a new record."""
        instance = self.model(**data)
        self.session.add(instance)
        await self.session.flush()   # Get ID without committing
        await self.session.refresh(instance)
        return instance

    async def update(
        self, record_id: UUID, data: Dict[str, Any]
    ) -> Optional[ModelType]:
        """Update an existing record by ID."""
        instance = await self.get_by_id(record_id)
        if not instance:
            return None
        for key, value in data.items():
            setattr(instance, key, value)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, record_id: UUID) -> bool:
        """Soft or hard delete a record. Returns True if deleted."""
        instance = await self.get_by_id(record_id)
        if not instance:
            return False
        await self.session.delete(instance)
        await self.session.flush()
        return True

    async def exists(self, record_id: UUID) -> bool:
        """Check if a record exists without loading the full object."""
        result = await self.session.execute(
            select(func.count())
            .select_from(self.model)
            .where(self.model.id == record_id)  # type: ignore
        )
        return result.scalar_one() > 0

"""Position domain rules and orchestration."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.positions.models import Position, PositionStatus
from app.modules.positions.repository import PositionRepository
from app.modules.positions.schemas import PositionCreate, PositionUpdate


class PositionService:
    """Enforce organizational-job invariants; positions never grant permissions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = PositionRepository(session)

    async def create(self, payload: PositionCreate) -> Position:
        code = self._normalize_code(payload.code)
        if await self._repository.get_by_code(code) is not None:
            raise ConflictError("Position code already exists.")

        position = Position(
            name=payload.name.strip(),
            code=code,
            description=payload.description,
            sort=payload.sort,
            status=PositionStatus(payload.status.value),
        )
        return await self._repository.create(position)

    async def get_active(self, position_id: UUID) -> Position:
        position = await self._repository.get_by_id(position_id)
        if position is None:
            raise NotFoundError("Position not found.")
        return position

    async def update(self, position_id: UUID, payload: PositionUpdate) -> Position:
        position = await self.get_active(position_id)
        changes = payload.model_dump(exclude_unset=True)

        if "code" in changes:
            normalized_code = self._normalize_code(changes["code"])
            existing = await self._repository.get_by_code(normalized_code)
            if existing is not None and existing.id != position.id:
                raise ConflictError("Position code already exists.")
            position.code = normalized_code
        if "name" in changes:
            position.name = changes["name"].strip()
        if "description" in changes:
            position.description = changes["description"]
        if "sort" in changes:
            position.sort = changes["sort"]
        if "status" in changes:
            position.status = PositionStatus(changes["status"].value)

        await self._session.flush()
        return position

    async def soft_delete(self, position_id: UUID) -> Position:
        position = await self.get_active(position_id)
        position.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return position

    @staticmethod
    def _normalize_code(code: str) -> str:
        normalized = code.strip().lower()
        if not normalized:
            raise ValidationError("Position code is required.")
        return normalized

"""Workspace, association, and menu persistence boundaries.

Repositories execute SQLAlchemy queries only: no HTTP, no authorization, no
commit (the request transaction or the calling service commits). Default
reads exclude soft-deleted rows, but nothing hides rows behind a global ORM
filter — history/administration queries can opt in explicitly via
``include_deleted``.
"""

from uuid import UUID

from app.modules.workspaces.models import Menu, Workspace, WorkspaceDepartment
from sqlalchemy import func, select
from sqlalchemy.engine import ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession


class WorkspaceRepository:
    """Workspace mirror-of-registry queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, workspace_id: UUID, *, include_deleted: bool = False
    ) -> Workspace | None:
        statement = select(Workspace).where(Workspace.id == workspace_id)
        if not include_deleted:
            statement = statement.where(Workspace.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def get_any_by_code(self, code: str) -> Workspace | None:
        """Code lookup across the full lifetime (codes are never reusable)."""

        return await self._session.scalar(select(Workspace).where(Workspace.code == code))

    async def get_by_code(self, code: str, *, include_deleted: bool = False) -> Workspace | None:
        statement = select(Workspace).where(Workspace.code == code)
        if not include_deleted:
            statement = statement.where(Workspace.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def list_active(self) -> list[Workspace]:
        statement = (
            select(Workspace)
            .where(
                Workspace.deleted_at.is_(None),
                Workspace.status == "active",
            )
            .order_by(Workspace.sort.asc(), Workspace.code.asc())
        )
        result = await self._session.scalars(statement)
        return list(result)

    async def list_mirrorable(self) -> list[Workspace]:
        """Rows the sync may touch: soft-deleted rows stay out of scope."""

        statement = select(Workspace).where(Workspace.deleted_at.is_(None))
        result = await self._session.scalars(statement)
        return list(result)

    async def create(self, workspace: Workspace) -> Workspace:
        self._session.add(workspace)
        await self._session.flush()
        return workspace


class WorkspaceDepartmentRepository:
    """Pure product/organization association queries; never an access grant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, workspace_id: UUID, department_id: UUID) -> WorkspaceDepartment | None:
        statement = select(WorkspaceDepartment).where(
            WorkspaceDepartment.workspace_id == workspace_id,
            WorkspaceDepartment.department_id == department_id,
        )
        return await self._session.scalar(statement)

    async def list_departments_for_workspace(self, workspace_id: UUID) -> list[UUID]:
        statement = (
            select(WorkspaceDepartment.department_id)
            .where(WorkspaceDepartment.workspace_id == workspace_id)
            .order_by(WorkspaceDepartment.department_id.asc())
        )
        result: ScalarResult[UUID] = await self._session.scalars(statement)
        return list(result)

    async def list_workspaces_for_department(self, department_id: UUID) -> list[UUID]:
        statement = (
            select(WorkspaceDepartment.workspace_id)
            .where(WorkspaceDepartment.department_id == department_id)
            .order_by(WorkspaceDepartment.workspace_id.asc())
        )
        result: ScalarResult[UUID] = await self._session.scalars(statement)
        return list(result)

    async def create(self, association: WorkspaceDepartment) -> WorkspaceDepartment:
        self._session.add(association)
        await self._session.flush()
        return association

    async def delete(self, association: WorkspaceDepartment) -> None:
        await self._session.delete(association)


class MenuRepository:
    """Menu navigation queries (adjacency list + recursive CTE)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, menu_id: UUID, *, include_deleted: bool = False) -> Menu | None:
        statement = select(Menu).where(Menu.id == menu_id)
        if not include_deleted:
            statement = statement.where(Menu.deleted_at.is_(None))
        return await self._session.scalar(statement)

    async def get_by_code(self, workspace_id: UUID, code: str) -> Menu | None:
        """Workspace-scoped code lookup; soft-deleted rows keep occupying codes."""

        return await self._session.scalar(
            select(Menu).where(Menu.workspace_id == workspace_id, Menu.code == code)
        )

    async def list_by_workspace(
        self, workspace_id: UUID, *, include_disabled: bool = True
    ) -> list[Menu]:
        statement = select(Menu).where(Menu.workspace_id == workspace_id, Menu.deleted_at.is_(None))
        if not include_disabled:
            statement = statement.where(Menu.status == "active")
        statement = statement.order_by(Menu.sort.asc(), Menu.code.asc())
        result = await self._session.scalars(statement)
        return list(result)

    async def count_for_workspace(self, workspace_id: UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(Menu)
            .where(Menu.workspace_id == workspace_id, Menu.deleted_at.is_(None))
        )
        return int(total or 0)

    async def descendant_ids(self, menu_id: UUID) -> list[UUID]:
        """Active-descendant lookup through a PostgreSQL recursive CTE."""

        subtree = (
            select(Menu.id)
            .where(Menu.id == menu_id, Menu.deleted_at.is_(None))
            .cte(name="menu_descendants", recursive=True)
        )
        subtree = subtree.union_all(
            select(Menu.id)
            .join(subtree, Menu.parent_id == subtree.c.id)
            .where(Menu.deleted_at.is_(None))
        )
        statement = select(subtree.c.id).where(subtree.c.id != menu_id).order_by(subtree.c.id.asc())
        result: ScalarResult[UUID] = await self._session.scalars(statement)
        return list(result)

    async def create(self, menu: Menu) -> Menu:
        self._session.add(menu)
        await self._session.flush()
        return menu

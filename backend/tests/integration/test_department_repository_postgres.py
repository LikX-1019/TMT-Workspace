"""Department persistence and recursive tree integration tests."""

import pytest
from app.core.exceptions import ValidationError
from app.modules.departments.models import Department
from app.modules.departments.schemas import DepartmentCreate
from app.modules.departments.service import DepartmentService
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


async def create_department(
    session: AsyncSession,
    *,
    name: str,
    code: str,
    parent_id=None,
) -> Department:
    service = DepartmentService(session)
    department = await service.create(DepartmentCreate(name=name, code=code, parent_id=parent_id))
    await session.commit()
    return department


async def test_department_tree_and_recursive_descendants(db_session: AsyncSession) -> None:
    root = await create_department(db_session, name="Company", code="company")
    child = await create_department(
        db_session,
        name="Technology",
        code="technology",
        parent_id=root.id,
    )
    grandchild = await create_department(
        db_session,
        name="Platform",
        code="platform",
        parent_id=child.id,
    )

    service = DepartmentService(db_session)
    tree = await service.tree()
    descendants = await service.descendant_ids(root.id)

    assert len(tree) == 1
    assert tree[0].id == root.id
    assert tree[0].children[0].id == child.id
    assert tree[0].children[0].children[0].id == grandchild.id
    assert set(descendants) == {child.id, grandchild.id}


async def test_department_rejects_self_parent(db_session: AsyncSession) -> None:
    service = DepartmentService(db_session)
    department = await service.create(DepartmentCreate(name="Self", code="self"))

    with pytest.raises(ValidationError, match="own parent"):
        await service.move(department.id, department.id)


async def test_department_move_to_descendant_is_rejected(db_session: AsyncSession) -> None:
    root = await create_department(db_session, name="Company", code="company")
    child = await create_department(
        db_session,
        name="Technology",
        code="technology",
        parent_id=root.id,
    )
    grandchild = await create_department(
        db_session,
        name="Platform",
        code="platform",
        parent_id=child.id,
    )

    service = DepartmentService(db_session)
    with pytest.raises(ValidationError, match="descendant"):
        await service.move(root.id, grandchild.id)


async def test_department_code_is_unique_across_soft_delete(db_session: AsyncSession) -> None:
    root = await create_department(db_session, name="Company", code="company")
    service = DepartmentService(db_session)
    await service.soft_delete(root.id)
    await db_session.commit()

    from app.core.exceptions import ConflictError

    with pytest.raises(ConflictError, match="code"):
        await service.create(DepartmentCreate(name="Company New", code="company"))


async def test_disabled_and_soft_deleted_departments_leave_normal_tree(
    db_session: AsyncSession,
) -> None:
    root = await create_department(db_session, name="Company", code="company")
    service = DepartmentService(db_session)
    await service.disable(root.id)
    await db_session.commit()

    assert await service.tree() == []
    department = await db_session.get(Department, root.id)
    assert department is not None
    assert department.status.value == "disabled"
    assert department.deleted_at is None

    await service.soft_delete(root.id)
    await db_session.commit()
    await db_session.refresh(department)
    assert department.deleted_at is not None

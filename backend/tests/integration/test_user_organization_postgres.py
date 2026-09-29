"""User identity and organization assignment integration tests."""

from uuid import UUID

import pytest
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.departments.schemas import DepartmentCreate
from app.modules.departments.service import DepartmentService
from app.modules.positions.schemas import PositionCreate
from app.modules.positions.service import PositionService
from app.modules.users.models import User, UserDepartment, UserPosition
from app.modules.users.schemas import UserCreate, UserUpdate
from app.modules.users.service import UserService
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.postgres


async def create_user(session: AsyncSession, *, username: str, employee_no: str) -> User:
    service = UserService(session)
    user = await service.create(
        UserCreate(
            username=username,
            employee_no=employee_no,
            name=username.title(),
            email=f"{username}@example.com",
        )
    )
    await session.commit()
    return user


async def test_user_unique_identifiers_and_optional_contact_fields(
    db_session: AsyncSession,
) -> None:
    first = await create_user(db_session, username="alice", employee_no="E001")
    assert first.email == "alice@example.com"

    service = UserService(db_session)
    optional = await service.create(
        UserCreate(username="bob", employee_no="E002", name="Bob", email=None, mobile=None)
    )
    await db_session.commit()

    assert optional.email is None
    assert optional.mobile is None
    with pytest.raises(ConflictError, match=r"(?i)email"):
        await service.create(
            UserCreate(
                username="email-copy",
                employee_no="E004",
                name="Email Copy",
                email="ALICE@example.com",
            )
        )
    with pytest.raises(ConflictError, match=r"(?i)employee number"):
        await service.create(
            UserCreate(username="alice-2", employee_no="E001", name="Duplicate Employee")
        )
    with pytest.raises(ConflictError, match=r"(?i)username"):
        await service.create(
            UserCreate(username="alice", employee_no="E003", name="Duplicate Username")
        )


async def test_user_supervisor_rules(db_session: AsyncSession) -> None:
    manager = await create_user(db_session, username="manager", employee_no="M001")
    employee = await create_user(db_session, username="employee", employee_no="E100")
    service = UserService(db_session)

    with pytest.raises(ValidationError, match="own supervisor"):
        await service.update(employee.id, UserUpdate(primary_supervisor_id=employee.id))

    updated = await service.update(
        employee.id,
        UserUpdate(primary_supervisor_id=manager.id),
    )
    await db_session.commit()
    assert updated.primary_supervisor_id == manager.id

    with pytest.raises(NotFoundError, match="Supervisor"):
        await service.update(
            employee.id,
            UserUpdate(primary_supervisor_id=UUID(int=0)),
        )


async def test_user_can_have_multiple_departments_but_one_primary(db_session: AsyncSession) -> None:
    user = await create_user(db_session, username="member", employee_no="E200")
    department_service = DepartmentService(db_session)
    root = await department_service.create(DepartmentCreate(name="Root", code="root"))
    child = await department_service.create(
        DepartmentCreate(name="Child", code="child", parent_id=root.id)
    )
    await db_session.commit()
    user_service = UserService(db_session)

    primary = await user_service.assign_department(user.id, root.id, is_primary=True)
    secondary = await user_service.assign_department(user.id, child.id, is_primary=False)
    await db_session.commit()
    assignments = await user_service.list_departments(user.id)

    assert len(assignments) == 2
    assert primary.is_primary is True
    assert secondary.is_primary is False
    assert assignments[0].department_id == root.id

    with pytest.raises(ConflictError, match="assignment"):
        await user_service.assign_department(user.id, root.id, is_primary=False)


async def test_user_department_partial_unique_index_is_database_backed(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session, username="primary-db", employee_no="E201")
    department_service = DepartmentService(db_session)
    first = await department_service.create(DepartmentCreate(name="First", code="first"))
    second = await department_service.create(DepartmentCreate(name="Second", code="second"))
    await db_session.commit()

    db_session.add_all(
        [
            UserDepartment(user_id=user.id, department_id=first.id, is_primary=True),
            UserDepartment(user_id=user.id, department_id=second.id, is_primary=True),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_user_can_have_multiple_positions_but_one_primary(db_session: AsyncSession) -> None:
    user = await create_user(db_session, username="worker", employee_no="E202")
    position_service = PositionService(db_session)
    developer = await position_service.create(PositionCreate(name="Developer", code="developer"))
    product = await position_service.create(PositionCreate(name="Product Manager", code="product"))
    await db_session.commit()
    user_service = UserService(db_session)

    primary = await user_service.assign_position(user.id, developer.id, is_primary=True)
    secondary = await user_service.assign_position(user.id, product.id, is_primary=False)
    await db_session.commit()

    assert primary.is_primary is True
    assert secondary.is_primary is False
    assert len(await user_service.list_positions(user.id)) == 2
    with pytest.raises(ConflictError, match="assignment"):
        await user_service.assign_position(user.id, developer.id, is_primary=False)


async def test_user_position_partial_unique_index_is_database_backed(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session, username="position-db", employee_no="E203")
    position_service = PositionService(db_session)
    first = await position_service.create(PositionCreate(name="First", code="first-position"))
    second = await position_service.create(PositionCreate(name="Second", code="second-position"))
    await db_session.commit()

    db_session.add_all(
        [
            UserPosition(user_id=user.id, position_id=first.id, is_primary=True),
            UserPosition(user_id=user.id, position_id=second.id, is_primary=True),
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

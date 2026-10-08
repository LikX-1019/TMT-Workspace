"""CLI bootstrap command contract against real PostgreSQL.

The sync ``main()`` entrypoint only wraps ``asyncio.run``; the command
function itself is exercised here because pytest already runs an event loop.
"""

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from app import cli
from app.cli import create_local_credential, main
from app.modules.auth.models import LocalCredential
from app.modules.users.models import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import committed_session
from tests.integration.test_auth_service_postgres import seed_user

pytestmark = pytest.mark.postgres

BOOTSTRAP_PASSWORD = "bootstrap-Passphrase-42"


@pytest.fixture(autouse=True)
async def fresh_process_engine() -> AsyncIterator[None]:
    """Rebuild the process-wide engine per test: asyncpg pools are loop-bound."""

    from app.db.session import dispose_engine

    await dispose_engine()
    try:
        yield
    finally:
        await dispose_engine()


async def get_credential(session: AsyncSession, username: str) -> LocalCredential | None:
    return await session.scalar(
        select(LocalCredential)
        .join(User, LocalCredential.user_id == User.id)
        .where(User.username == username)
    )


class TestCreateLocalCredential:
    async def test_creates_first_credential_for_existing_user(self) -> None:
        async with committed_session() as session:
            await seed_user(session, username="cli-user", with_credential=False)
            await session.commit()

        exit_code = await create_local_credential(
            username="cli-user",
            employee_no=None,
            password=BOOTSTRAP_PASSWORD,
            must_change_password=False,
        )

        assert exit_code == 0
        async with committed_session() as session:
            credential = await get_credential(session, "cli-user")
            assert credential is not None
            assert credential.password_hash.startswith("$argon2id$")
            assert BOOTSTRAP_PASSWORD not in credential.password_hash

    async def test_locates_user_by_employee_no(self) -> None:
        async with committed_session() as session:
            await seed_user(session, username="cli-empno", with_credential=False)
            await session.commit()

        exit_code = await create_local_credential(
            username=None,
            employee_no="E-cli-empno",
            password=BOOTSTRAP_PASSWORD,
            must_change_password=False,
        )

        assert exit_code == 0
        async with committed_session() as session:
            assert await get_credential(session, "cli-empno") is not None

    async def test_refuses_second_credential(self) -> None:
        async with committed_session() as session:
            await seed_user(session, username="cli-existing")
            await session.commit()

        exit_code = await create_local_credential(
            username="cli-existing",
            employee_no=None,
            password=BOOTSTRAP_PASSWORD,
            must_change_password=False,
        )

        assert exit_code == 1

    async def test_fails_when_user_missing(self) -> None:
        exit_code = await create_local_credential(
            username="ghost-cli",
            employee_no=None,
            password=BOOTSTRAP_PASSWORD,
            must_change_password=False,
        )

        assert exit_code == 1

    async def test_enforces_password_policy(self) -> None:
        async with committed_session() as session:
            await seed_user(session, username="cli-policy", with_credential=False)
            await session.commit()

        exit_code = await create_local_credential(
            username="cli-policy",
            employee_no=None,
            password="cli-policy",
            must_change_password=False,
        )

        assert exit_code == 1
        async with committed_session() as session:
            assert await get_credential(session, "cli-policy") is None


class TestCliEntrypoint:
    def test_main_requires_username_or_employee_no(self) -> None:
        with pytest.raises(SystemExit):
            main(["create-local-credential"])

    def test_prompt_requires_matching_confirmation(self) -> None:
        with (
            patch.object(cli.getpass, "getpass", side_effect=["secret-one", "secret-two"]),
            pytest.raises(ValueError, match="do not match"),
        ):
            cli._prompt_password()

    def test_prompt_reads_interactively_without_echo(self) -> None:
        with patch.object(
            cli.getpass,
            "getpass",
            side_effect=["typed-password-1", "typed-password-1"],
        ) as prompts:
            password = cli._prompt_password()

        assert password == "typed-password-1"
        assert prompts.call_count == 2

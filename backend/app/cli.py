"""Operational CLI for developer and bootstrap tasks.

Run through ``uv run --directory backend python -m app.cli <command>``.
Passwords are only ever read interactively; command arguments never carry
plaintext credentials so they cannot leak into shell history. RBAC commands
(``sync-permissions``, ``sync-workspaces``, ``assign-role``) are explicit
operator actions so the application never writes catalog/registry data at
startup.
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from app.core.exceptions import AppError, PasswordPolicyError
from app.core.security import hash_password, validate_password_policy
from app.db.base import utc_now
from app.db.session import get_session_factory
from app.modules.auth.models import LocalCredential
from app.modules.auth.repository import LocalCredentialRepository
from app.modules.rbac.service import AuthorizationService, PermissionCatalogService
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.workspaces.service import WorkspaceRegistryService


async def create_local_credential(
    *,
    username: str | None,
    employee_no: str | None,
    password: str,
    must_change_password: bool,
) -> int:
    """Attach the first local credential to an existing employee identity."""

    async with get_session_factory()() as session:
        repository = UserRepository(session)
        user: User | None
        if username is not None:
            user = await repository.get_by_username(username)
        else:
            user = await repository.get_by_employee_no(employee_no) if employee_no else None
        if user is None:
            print("User not found; create the employee identity first.", file=sys.stderr)
            return 1

        credentials = LocalCredentialRepository(session)
        if await credentials.get_by_user_id(user.id) is not None:
            print(
                f"User '{user.username}' already has a local credential; "
                "this command only issues first credentials.",
                file=sys.stderr,
            )
            return 1

        try:
            validate_password_policy(
                password,
                username=user.username,
                employee_no=user.employee_no,
                email=user.email,
            )
        except PasswordPolicyError as error:
            print(str(error), file=sys.stderr)
            return 1

        await credentials.create(
            LocalCredential(
                user_id=user.id,
                password_hash=hash_password(password),
                password_changed_at=utc_now(),
                must_change_password=must_change_password,
            )
        )
        await session.commit()
        print(f"Local credential created for '{user.username}'.")
        return 0


async def sync_permissions(*, dry_run: bool) -> int:
    """Mirror the code-owned permission catalog into the database."""

    async with get_session_factory()() as session:
        service = PermissionCatalogService(session)
        report = await service.sync(dry_run=dry_run)

        prefix = "[dry-run] " if dry_run else ""
        for code in report.created:
            print(f"{prefix}create:    {code}")
        for code in report.updated:
            print(f"{prefix}update:    {code}")
        for code in report.reenabled:
            print(f"{prefix}re-enable: {code}")
        for code in report.stale_disabled:
            print(f"{prefix}stale:     {code} (disabled; row kept for history)")
        for code in report.roles_created:
            print(f"{prefix}role:      {code} (system role seeded)")
        for grant in report.role_permissions_added:
            print(f"{prefix}grant:     {grant}")

        print(
            f"{prefix}summary: {len(report.created)} created, {len(report.updated)} updated, "
            f"{len(report.reenabled)} re-enabled, {len(report.stale_disabled)} stale, "
            f"{len(report.unchanged)} unchanged, {len(report.roles_created)} roles seeded, "
            f"{len(report.role_permissions_added)} role-permission grants added"
        )

        if not dry_run:
            await session.commit()
            print("Permission catalog synchronized.")
        return 0


async def sync_workspaces(*, dry_run: bool) -> int:
    """Mirror the code-owned workspace registry into the database."""

    async with get_session_factory()() as session:
        service = WorkspaceRegistryService(session)
        report = await service.sync(dry_run=dry_run)

        prefix = "[dry-run] " if dry_run else ""
        for code in report.created:
            print(f"{prefix}create:    {code}")
        for code in report.updated:
            print(f"{prefix}update:    {code}")
        for code in report.stale_disabled:
            print(f"{prefix}stale:     {code} (disabled; row kept for history)")
        for code in report.unchanged:
            print(f"{prefix}unchanged: {code}")

        print(
            f"{prefix}summary: {len(report.created)} created, {len(report.updated)} updated, "
            f"{len(report.stale_disabled)} stale, {len(report.unchanged)} unchanged"
        )

        if not dry_run:
            await session.commit()
            print("Workspace registry synchronized.")
        return 0


async def assign_role(*, username: str, role_code: str, assigned_by_username: str | None) -> int:
    """Grant an existing role to an existing user (idempotent)."""

    async with get_session_factory()() as session:
        users = UserRepository(session)
        user = await users.get_by_username(username)
        if user is None:
            print(f"User '{username}' not found.", file=sys.stderr)
            return 1
        if user.deleted_at is not None:
            print(f"User '{username}' is soft-deleted; roles cannot be assigned.", file=sys.stderr)
            return 1

        assigned_by: User | None = None
        if assigned_by_username is not None:
            assigned_by = await users.get_by_username(assigned_by_username)
            if assigned_by is None:
                print(f"Assigning user '{assigned_by_username}' not found.", file=sys.stderr)
                return 1

        authorization = AuthorizationService(session)
        try:
            _role_id, newly_assigned = await authorization.assign_role(
                user.id, role_code, assigned_by=assigned_by.id if assigned_by else None
            )
        except AppError as error:
            print(str(error), file=sys.stderr)
            return 1

        await session.commit()
        if newly_assigned:
            print(f"Role '{role_code}' assigned to '{user.username}'.")
        else:
            print(f"User '{user.username}' already has role '{role_code}'; nothing changed.")
        return 0


async def _print_user_roles(username: str) -> int:
    async with get_session_factory()() as session:
        users = UserRepository(session)
        user = await users.get_by_username(username)
        if user is None:
            print(f"User '{username}' not found.", file=sys.stderr)
            return 1
        authorization = AuthorizationService(session)
        codes = await authorization.get_role_codes(user.id)
        if not codes:
            print(f"User '{user.username}' holds no active roles.")
            return 0
        for code in codes:
            print(code)
        return 0


def _prompt_password() -> str:
    password = getpass.getpass("Set password: ")
    confirmed = getpass.getpass("Confirm password: ")
    if password != confirmed:
        raise ValueError("Passwords do not match.")
    if not password:
        raise ValueError("Password must not be empty.")
    return password


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="TMT Workspace operations CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    credential = commands.add_parser(
        "create-local-credential",
        help="Attach the first local password credential to an existing user",
    )
    target = credential.add_mutually_exclusive_group(required=True)
    target.add_argument("--username", help="Username of the existing user")
    target.add_argument("--employee-no", help="Employee number of the existing user")
    credential.add_argument(
        "--must-change-password",
        action="store_true",
        help="Force a password change on next login workflows",
    )

    sync = commands.add_parser(
        "sync-permissions",
        help="Synchronize the code-owned permission catalog and system roles",
    )
    sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the plan without writing any database changes",
    )

    workspace_sync = commands.add_parser(
        "sync-workspaces",
        help="Synchronize the code-owned workspace registry into the database",
    )
    workspace_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the plan without writing any database changes",
    )

    assign = commands.add_parser("assign-role", help="Assign an existing role to a user")
    assign.add_argument("--username", required=True, help="Username receiving the role")
    assign.add_argument("--role", required=True, help="Stable role code (e.g. super_admin)")
    assign.add_argument(
        "--assigned-by",
        help="Username recording the acting administrator (optional evidence)",
    )

    roles = commands.add_parser("show-user-roles", help="List a user's active role codes")
    roles.add_argument("--username", required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "create-local-credential":
        try:
            password = _prompt_password()
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
        return asyncio.run(
            create_local_credential(
                username=args.username,
                employee_no=args.employee_no,
                password=password,
                must_change_password=args.must_change_password,
            )
        )
    if args.command == "sync-permissions":
        return asyncio.run(sync_permissions(dry_run=args.dry_run))
    if args.command == "sync-workspaces":
        return asyncio.run(sync_workspaces(dry_run=args.dry_run))
    if args.command == "assign-role":
        return asyncio.run(
            assign_role(
                username=args.username,
                role_code=args.role,
                assigned_by_username=args.assigned_by,
            )
        )
    if args.command == "show-user-roles":
        return asyncio.run(_print_user_roles(args.username))
    return 2  # pragma: no cover - argparse rejects unknown commands first


if __name__ == "__main__":
    raise SystemExit(main())

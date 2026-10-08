# TMT Workspace AI Coding Rules

These rules apply to every AI agent and human contributor working in this repository. They are intentionally stricter than general style advice: this platform will host multiple business workspaces, and consistency is a functional requirement.

## Prime Directives

1. Read before writing. Inspect the affected module, tests, migrations, and relevant documentation before changing code.
2. Preserve module boundaries. Do not invent hidden coupling or convenience imports between business modules.
3. Prefer boring, explicit, testable Python. Do not introduce frameworks, event buses, CQRS, microservices, or speculative abstractions.
4. Do not disable authentication, authorization, validation, SQL protections, linting, type checks, or tests to make a task easier.
5. Do not claim completion unless `make check` passes or the blocker is explicitly reported.

## Repository Map

```text
frontend/
  src/api/         # HTTP client wrappers and typed response contracts
  src/layouts/     # Application shell
  src/router/      # Static shell routes; dynamic routes remain backend-driven
  src/stores/      # Pinia state
  src/modules/     # System/public feature views and module-scoped components
  src/workspaces/  # Workspace entry placeholders; canonical codes fixed by the backend registry

backend/
  app/api/         # Composition of versioned routers only
  app/core/        # Configuration, security, logging, exceptions, shared policy
  app/common/      # Canonical response, pagination, DTO, and utility contracts
  app/db/          # Engine, session, ORM base, model registry, shared mixins
  app/modules/     # Business/platform modules; each owns its vertical slice
  app/integrations/ # Isolated third-party provider adapters
  migrations/      # Async Alembic migrations
  tests/           # Unit, API, integration, and permission tests

docs/              # Durable architecture and decision documentation
infra/             # Nginx, deployment assets, and operational scripts
```

## Architecture Rules

### Module boundary

Each backend module under `backend/app/modules/<module_name>/` should organize code explicitly:

```text
backend/app/modules/<module_name>/
  api.py           # HTTP routing, dependency wiring, status codes
  schemas.py       # Request/response DTOs
  service.py       # Application rules and orchestration
  models.py        # SQLAlchemy persistence model
  repository.py    # Query/persistence access for this aggregate
```

Small modules may temporarily combine adjacent files only when the boundary remains obvious. Do not create Manager, Helper, Util, or Common modules that silently become god objects.

### Dependency direction

```text
api -> service -> repository -> SQLAlchemy
schemas -> api/service (as DTO boundaries)
modules -> core/db (shared infrastructure)
```

Required restrictions:

- API routers must not execute ORM queries directly.
- Services must not parse HTTP requests or construct HTTP responses.
- Repositories must not contain cross-aggregate business policy.
- Modules must not import another module's private `_service`, `_repository`, or model internals.
- When module A needs data from module B, expose a small public service method or DTO contract and document the dependency.
- Circular imports are an architecture defect, not an import-order problem.

### Application service layer

A service is the transaction boundary and the place where authorization intent, invariants, audit intent, and workflow order are made explicit. It receives typed inputs and returns domain objects or DTOs. It must be independently testable without HTTP.

Repositories contain persistence-specific logic. They receive `AsyncSession`, return ORM objects or typed projection rows, and do not commit unless the repository contract explicitly documents that behavior. The default request transaction commits in `get_db_session`.

### Workspace versus domain capability

`src/workspaces/<name>/` is frontend navigation and access composition only. It is not a backend domain boundary.

Backend module names must describe actual business capabilities, such as `products`, `orders`, `inventory`, `advertising`, or `reports`. Do not create `modules/operation`, `modules/finance`, or another workspace-named module by default. A workspace may compose multiple domain capabilities.

## Python Rules

- Target Python 3.12+.
- Use modern typing everywhere: `str | None`, `list[str]`, `dict[str, int]`, and typed `TypeVar` when necessary.
- Every public function, class, and method must have annotations. `mypy --strict` must pass.
- Use `async def` for I/O-bound API and repository paths. Do not call blocking I/O in async functions; move blocking work to a worker or explicitly documented synchronous boundary.
- Prefer dependency injection over globals. The only process-wide singletons are the configured engine/session factory and settings cache.
- Names use `PascalCase` for types, `snake_case` for functions/variables, `UPPER_SNAKE_CASE` for constants, and singular module names where possible.
- First-party backend imports begin with `app.`. Do not introduce `backend.app` as an import namespace.
- Exceptions must derive from `AppError` for expected failures. Do not use exceptions for ordinary control flow.
- Docstrings explain contracts, invariants, and non-obvious behavior. Do not narrate every obvious line.
- Imports are grouped by standard library, third party, and first-party and sorted by Ruff.

## FastAPI Rules

- All versioned routers are mounted under `/api/v1`.
- API functions validate input with Pydantic schemas and declare response models.
- Authentication and permissions must be injected through reusable FastAPI dependencies; never read authorization state from ad hoc headers in individual routes.
- Return `SuccessEnvelope[T]` from successful API operations.
- Expected failures raise `AppError` subclasses and are translated centrally.
- Use precise status codes: `200` for success, `201` for creation, `400` for malformed request semantics, `401` for unauthenticated, `403` for unauthorized, `404` for hidden or absent resource, `409` for conflict, and `422` for validation failure.
- Do not expose stack traces, SQL, internal IDs of unrelated systems, or secrets in API errors.

## Database Rules

- PostgreSQL and SQLAlchemy 2.x with `AsyncSession` are the default.
- Schema changes require an Alembic migration. Never edit an already-applied migration.
- Every table uses explicit primary keys, foreign keys, indexes, and unique constraints where appropriate.
- Shared `TimestampMixin` stores timezone-aware UTC timestamps.
- Prefer `UUID` surrogate keys for core platform entities unless a documented business identifier is required.
- Foreign keys are mandatory for relationships. Use `ondelete` deliberately; do not rely on cascade by accident.
- Users, employees, departments, roles, and audit records are never physically deleted. Disable, archive, or supersede them.
- Soft delete uses `deleted_at` when historical identity must remain queryable. Status fields represent lifecycle state, not deletion.
- Repository queries must use SQLAlchemy expressions or bound parameters. String-concatenated SQL is prohibited.
- Multi-tenant/workspace isolation and data scope conditions belong in repository/service query construction, not optional frontend checks.

## Permission Rules

Every new endpoint or business operation must document and enforce:

```text
workspace: which workspace it belongs to
permission code: <workspace>:<resource>:<action>
role access: which roles receive the permission
data scope: all / department / department-and-children / self / custom
```

Permission codes are lowercase, colon-delimited, stable identifiers. Resource and action names use kebab-case only when a hyphen is clearer. Examples:

```text
system:user:list
system:user:create
system:user:update
system:user:disable
workspace:operation:access
operation:product:create
```

Implementation state (Phase 2A):

- Permission codes are a **code-owned catalog** in `app/modules/rbac/catalog.py`. Add new codes there (with a future enforcement point), never directly in the database; `python -m app.cli sync-permissions` mirrors the catalog, and `--dry-run` previews changes. Removed codes are disabled and reported stale, never deleted.
- `AuthorizationService` resolves roles and effective permission codes (union of active grants/roles/permissions; no deny semantics). It must stay free of HTTP, workspace, menu, and data-scope logic.
- `super_admin` is a normal system role resolved dynamically to all active permissions — never express platform powers as username/ID comparisons.
- System roles are protected from ordinary disable/delete; role soft-delete keeps `user_roles` history.

Enforcement (Phase 2B):

- `require_permission(...)` lives in `app/modules/rbac/dependencies.py` and is the only way to gate an endpoint. It builds on `get_current_user` (authentication stays separate), resolves an `AuthorizationContext` once per request, and answers through `AuthorizationService` — the dependency itself never encodes role or super-admin rules.
- Business code must pass catalog constants (`Permissions.USER_LIST`), not scattered string literals. `require_permission` fails fast at dependency-construction time for codes outside the catalog — a typo is a programming error, not a runtime 403.
- Every newly added protected backend endpoint MUST declare its permission code; "the page hides the button" never replaces a backend check.
- Every new management endpoint MUST ship three tests: allowed, denied, and unauthenticated.
- No permission cache: effective permissions are read from PostgreSQL per request; changes take effect on the next request.

Workspaces and menus (Phase 3A):

- A workspace may exist only if it is declared first in the code-owned `Workspace Registry` (`app/modules/workspaces/registry.py`). The database mirrors the registry through `python -m app.cli sync-workspaces` (`--dry-run` previews; stale rows are disabled, never deleted; application startup never writes registry data).
- A workspace `code` is a stable software identifier. It becomes part of permission codes, menus, role grants, and external integrations — it is immutable for the full lifetime of the workspace (soft-deleted rows keep occupying their code).
- Runtime creation of arbitrary workspace codes is prohibited. `WorkspaceService` has no create path; the registry sync is the only writer.
- Backend domains MUST NOT be organized by workspace directory names (`modules/operation`, `modules/finance` for workspace reasons are forbidden). Workspaces compose backend capabilities; they do not define them. System Management is platform capability, never a business workspace.
- Workspace access MUST use the unified RBAC path: `workspace:<workspace_code>:access` permission codes are derived deterministically from the registry into the permission catalog (`sync-permissions` writes them) and reach users only through `UserRole → Role → RolePermission`. No `role_workspaces`/`user_workspaces` second authorization system is allowed.
- `WorkspaceDepartment` is product/organization metadata only. It MUST NOT be treated as an access grant, and department membership must never imply workspace access.
- `menu.permission_code` controls UI/navigation visibility only. It must reference an active catalog code (unknown codes are rejected at the service boundary), and the backend must never trust menu visibility as authorization.
- Menu trees are navigation only (`directory`/`page`); button/action permissions are not menu rows.

Rules:

- Users acquire permissions through roles. Direct user-permission grants are prohibited.
- Positions describe organizational jobs and must never be used as authorization roles.
- Menus may reference permission codes, but frontend visibility is not authorization.
- Backend dependencies must check action permission, workspace access, and applicable data scope (workspace checks: Phase 3; data-scope enforcement: dedicated later phase).
- Sensitive actions require audit logging at the service layer.

## Security Rules

AI agents must never:

- Store plaintext passwords.
- Log passwords, tokens, refresh tokens, secrets, full personal identifiers, or credential headers.
- Hard-code secrets in source, tests, fixtures, or docs.
- Bypass RBAC or data-scope checks.
- Add debug backdoors.
- Build SQL by string interpolation.
- Trust client-provided role, workspace, department, or user identity fields for authorization.

Use bcrypt/argon2 through a maintained library, short-lived access tokens, rotated refresh tokens, server-side session/token revocation state, password policies, brute-force controls, and masked audit fields as they are introduced.

## Testing Rules

Any behavior-bearing change requires tests. Core and security code requires integration coverage.

Minimum expectations:

- API contract tests for request/response and status codes.
- Unit tests for service rules.
- Database tests for migrations, constraints, and repository queries.
- Permission tests for both allowed and denied paths, including workspace and data-scope denial.
- Regression tests for every fixed bug.

Test names should describe the behavior. Arrange/act/assert structure should remain obvious.

## Documentation Rules

Update documentation in the same change when you:

- alter architecture or module boundaries,
- add or rename an entity or relationship,
- introduce a permission code,
- change an API contract,
- add infrastructure,
- alter security behavior,
- add a development workflow requirement.

For database changes, update `docs/database/DATABASE_DESIGN.md` and the RBAC/data-scope docs when applicable.

## Language Rules

All deliverables produced by AI agents follow this language split:

- **Chinese**: all code comments and docstrings (backend Python, frontend TypeScript/Vue, infra scripts, migration docstrings), deliverable reports, and review summaries.
- **English stays as-is**: code itself — identifiers, function/type/variable names, string literals that are contract data (permission codes, log keys, error codes), and tooling/configuration keywords.

Rules:

- User-visible AI output (analysis, plans, progress reports, architecture explanations, risk notes, validation results, final reports) defaults to Simplified Chinese. English versions are produced only when explicitly requested.
- Code and stable technical identifiers stay English.
- Git commit messages keep English Conventional Commits.
- Never change existing code's language retroactively; the rule applies to new and modified code from now on.
- Comments explain contracts, invariants, and non-obvious behavior in Chinese; keep technical terms (table names, class names, HTTP status names) in their original English form inside Chinese sentences.
- User-facing copy in the frontend is already product Chinese; do not mix English sentences into it.
- OpenAPI descriptions and validation messages count as deliverable text: write them in Chinese unless a client contract explicitly requires English.

## Required Validation

Before reporting a task complete, run:

```bash
make check
```

This executes backend Ruff format check, Ruff lint, MyPy, Pytest, and the frontend type-checked production build. If a tool cannot run, report the exact command, error, and remaining risk. Do not silently declare partial success.

## AI Change Workflow

1. **Read** the affected code and documentation.
2. **Understand** the existing architecture and contracts.
3. **Plan** the smallest safe change and identify tests.
4. **Implement** using existing patterns.
5. **Test** behavior, permissions, failure paths, and constraints.
6. **Lint and type check**.
7. **Review the full diff** for accidental scope, secrets, logs, and breaking contracts.
8. **Document** durable decisions and update migrations/OpenAPI as required.

AI agents must not expand a task into unrelated refactoring. If a necessary prerequisite is missing, state the decision made and record it in the relevant documentation.

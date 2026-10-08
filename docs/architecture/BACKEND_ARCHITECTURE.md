# Backend Architecture

## Application Shape

The backend is a modular monolith under `backend/app`. It is one deployable unit, but each platform/business module owns its HTTP interface, DTOs, service rules, persistence model, repository queries, permission dependencies, and tests. First-party imports always start with `app`.

In Phase 1A, `departments`, `positions`, and `users` intentionally implement models, schemas, repositories, and services without `api.py` files or management routes. Phase 1B adds the `auth` module as the first authenticated API surface: `login`, `refresh`, `logout`, and `me`, plus the shared `get_current_user` dependency. Organization mutation routes stay unwritten until the permission dependencies of Phase 2 exist; health routes and the four auth routes are the only public API surface.

Phase 2A adds the `rbac` module beside it — persistence, catalog sync, and authorization *resolution* (no HTTP surface yet; `require_permission(...)` dependencies are Phase 2B):

```text
app/modules/rbac/
  models.py        # Role, Permission, UserRole, RolePermission
  catalog.py       # code-owned SYSTEM_PERMISSIONS / Permissions constants / CATALOG_PERMISSION_CODES
  repository.py    # set-based persistence and resolution queries
  service.py       # RoleService, PermissionCatalogService, AuthorizationService
  dependencies.py  # require_permission(...) + request-scoped AuthorizationContext
```

Phase 2B adds the enforcement edge: `require_permission` composes
`get_current_user` (authentication) with the context resolved through
`AuthorizationService` (authorization), validates codes against the catalog at
construction time (fail fast), and raises `AuthorizationError` on denial. One
protected request performs two set-based reads (roles, permissions) — no N+1 —
and writes nothing.

The documented cross-module dependency: `auth` consumes the `rbac` public
`AuthorizationService` contract (role codes + effective permissions for
`/auth/me`). `rbac` never imports `auth`. `AuthorizationService` answers
"what can this user do?" — it must never grow HTTP, workspace, menu, or
data-scope responsibilities; those belong to future dependencies/phases.

Phase 2C completes the management surface by adding `api.py` files to the
`users`, `departments`, `positions`, and `rbac` modules. Every endpoint is a
thin composition layer: permission dependency (`require_permission` with a
catalog constant) + typed Pydantic input + service call + `SuccessEnvelope`
response. Routers never execute queries against the session; DTO/model enum
conversion happens in the API layer. Cross-module composition stays on public
contracts only (`users` router uses `rbac`'s `AuthorizationService` for the
role-assignment endpoints; `rbac` never imports `users`). Phase 2C adds no
schema change — it is pure service/API composition over Phase 1A/2A tables.

```text
app/modules/users/api.py        # /users CRUD + lifecycle + /users/{id}/roles (assignment)
app/modules/departments/api.py  # /departments CRUD + tree + move + lifecycle
app/modules/positions/api.py    # /positions CRUD + lifecycle (no RBAC side effects)
app/modules/rbac/api.py         # /roles CRUD + /roles/{id}/permissions + read-only /permissions
```

Phase 3A adds the `workspaces` module as persistence + registry foundation with
**no HTTP surface** (no management API, no navigation endpoint — Phase 3B):

```text
app/modules/workspaces/
  registry.py    # code-owned WorkspaceDefinition list + grammar validation (no imports from rbac/db)
  models.py      # Workspace, WorkspaceDepartment, Menu
  repository.py  # WorkspaceRepository, WorkspaceDepartmentRepository, MenuRepository (recursive CTE)
  service.py     # WorkspaceRegistryService (sync), WorkspaceService, MenuService
  schemas.py     # future API DTOs (no routes mounted in Phase 3A)
```

Two deliberate dependency decisions:

- `registry.py` stays dependency-free so `rbac.catalog` can consume it (the
  catalog merges registry-derived `workspace:<code>:access` definitions into
  `SYSTEM_PERMISSIONS`); this is the documented rbac → workspaces.registry
  public-contract dependency, and no reverse import exists.
- `MenuService` validates `menu.permission_code` through the rbac public
  `PermissionRepository`/catalog codes (workspaces → rbac public contract);
  `WorkspaceDepartment` never touches authorization aggregates.

The `auth` module structure is the reference for later modules:

```text
app/modules/auth/
  api.py           # /auth/login|refresh|logout|me; cookie handling; Origin validation
  schemas.py       # LoginRequest, TokenResponse, CurrentUserResponse
  service.py       # AuthService: credential checks, rotation, revocation, throttling policy
  models.py        # LocalCredential, RefreshToken, LoginLog
  repository.py    # Credential/refresh-token/login-log persistence
  dependencies.py  # get_current_user and friends for every other module
  redis_store.py   # AuthStateStore protocol + Redis implementation (counters, revoked sessions)
```

Two durability rules in `auth` are deliberate and reused later:

- security-critical writes (revocation, reuse detection, login evidence) commit inside the service or through an independent session so a rolled-back request cannot erase them;
- repositories never commit; only `AuthService` decides transaction boundaries, except the `LoginLogWriter`, whose independent session is its documented contract.

```text
app/api/v1/router.py       # Router composition only
app/common/                # Response envelope, pagination, shared DTOs
app/core/                  # Settings, logging, exceptions, future security dependencies
app/db/                    # Engine, session, Base, mixins, model registry
app/modules/<module>/      # Vertical business/platform modules
app/integrations/<provider>/ # Isolated external adapters
backend/migrations/        # Alembic revisions
backend/tests/             # Backend test suite
```

## Request Flow

```text
FastAPI dependency graph
  -> API route
  -> authentication / workspace / action permission dependencies
  -> typed request schema
  -> application service
  -> repository and scoped SQLAlchemy query
  -> typed response schema
```

The API layer does not execute queries. Services do not depend on FastAPI request/response types. Repositories do not own other aggregates. Shared transaction behavior commits in `app.db.session.get_db_session` after successful request handling and rolls back on exceptions.

## Module Contract

A new backend module should expose:

```text
__init__.py
api.py          # Routes, status codes, dependency wiring
schemas.py      # Pydantic request/response DTOs
service.py      # Application rules and transaction intent
models.py       # SQLAlchemy tables
repository.py   # Persistence/query boundary
dependencies.py # Only when the module has reusable route dependencies
tests.py        # Or a mirror under backend/tests
```

Register a module router only when the module has an authenticated API contract; register model modules in `app/db/models.py`. Never wire one module directly to another module's private internals.

## Infrastructure Responsibilities

- **PostgreSQL** is the authoritative data store.
- **Redis** holds login-throttling counters and revoked-session markers (Phase 1B); later it also serves cache, rate limiting, locks, and task coordination. Permission resolution deliberately stays on PostgreSQL in Phase 2A until profiling justifies a cache plus invalidation.
- **Alembic** owns all schema changes.
- **Ruff/MyPy/Pytest** are the backend correctness gate.
- **Docker Compose** supports local dependencies and integrated startup; it does not imply a production orchestration decision.

## Stability Rules

- Keep `/api/v1` contracts backward compatible.
- Keep permission checks and data scope in backend dependencies/services/repositories.
- Keep every module independently understandable.
- Keep configuration in `app.core.config`; do not scatter environment reads.
- Make new infrastructure optional until a phase requires it.

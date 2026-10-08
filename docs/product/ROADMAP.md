# Roadmap

## Phase 0: Architecture And Repository Bootstrap

**Status: complete**

Goals:

- establish modular monolith architecture;
- establish FastAPI/SQLAlchemy conventions;
- establish the Vue 3 console shell and frontend module boundaries;
- establish configuration, health API, response/error contracts;
- prepare async Alembic foundation;
- establish security-first RBAC/data-scope design;
- establish AI coding and validation rules.

Exit criteria:

- repository runs;
- `make check` passes;
- architecture and platform policies are documented;
- future phases can proceed without redesigning module boundaries.

## Phase 0.5: Foundation Hardening

**Status: complete**

Goals:

- make the `TMT_` configuration contract explicit and test it;
- enforce explicit-secret policy for development/production;
- remove the obsolete nested Python source layout;
- freeze the browser token contract before authentication exists;
- clarify workspace navigation versus backend domain capability boundaries;
- make adjacency plus recursive CTE the first department hierarchy implementation;
- split organization/identity work from authentication work.

Exit criteria:

- configuration override and secret-policy tests pass;
- frontend contains no token browser-storage contract;
- architecture and security documents agree;
- repository has no obsolete Python package path;
- `make check` and `docker compose config` pass.

## Phase 1A: Organization And Identity Persistence Foundation

**Status: complete**

Goals:

- create initial database migrations;
- implement Department model, repository, service, and schemas without management HTTP APIs;
- implement Position model and assignment relationships;
- implement User model with no physical delete;
- implement user-department relationships with a current primary assignment;
- implement user-position relationships;
- implement first-level/recursive department tree reads with PostgreSQL CTEs;
- provide the first Alembic migration plus repository/service/schema and PostgreSQL test coverage.

Explicit exclusions:

- password hashing;
- login;
- JWT;
- access-token dependencies;
- refresh cookies;
- logout;
- current-user endpoint;
- account-state authentication checks;
- login logs;
- brute-force protection.

Primary tests:

- duplicate username/email/employee number;
- department cycle prevention;
- department parent/child/grandchild recursive lookup;
- only one current primary department assignment;
- user/department/position soft-delete and historical retention behavior.
- automated Alembic upgrade/downgrade/upgrade against PostgreSQL 16.

## Phase 1B: Authentication

**Status: complete**

Delivered:

- Argon2id password hashing (`pwdlib`) with policy validation and transparent legacy-parameter rehash;
- local login with generic failures, dummy verification, and account-state gating (`on_leave` allowed; disabled/locked/resigned/soft-deleted denied);
- 30-minute HS256 access tokens with `sub`/`typ`/`sid`/`iat`/`exp`/`jti` claims;
- refresh tokens as opaque `HttpOnly`, `SameSite=Lax`, `Secure`-in-production cookies scoped to `/api/v1/auth`, stored as SHA-256 lookup hashes;
- transactional refresh rotation with row locks, lineage (`replaced_by_id`), and family-wide reuse detection plus Redis revoked-session markers;
- logout with idempotent response, cookie clearing, and immediate access-token invalidation;
- `/auth/me` current-user endpoint (identity, status, primary department/position; roles arrive in Phase 2);
- `login_logs` authentication evidence written through an independent session;
- Redis username/IP brute-force throttling (default 10 failures / 300 s);
- CLI bootstrap of the first local credential (`python -m app.cli create-local-credential`);
- frontend session bootstrap, single-flight 401 refresh interceptor, runtime-memory token storage, and router guard;
- PostgreSQL/Redis integration suites, Vitest frontend suite, and migration upgrade/downgrade/upgrade verification.

Primary tests:

- authentication success/failure;
- expired/revoked/reused refresh token;
- refresh cookie is HttpOnly, Secure, SameSite, and never exposed in JSON;
- disabled/resigned account cannot authenticate or retain access;
- logout revokes the token family;
- brute-force lockout/throttling.

## Phase 2A: RBAC Persistence & Permission Catalog

**Status: complete**

Delivered:

- `roles`, `permissions`, `user_roles`, `role_permissions` tables (migration `0003_rbac_foundation`, PostgreSQL-only, upgrade/downgrade/upgrade verified);
- code-owned permission catalog (`app/modules/rbac/catalog.py`, 23 `system:*` action codes) with grammar validation in unit tests;
- explicit `sync-permissions` CLI with `--dry-run`, stable ids/codes, stale-disable semantics, and system-role seeding (`super_admin`, `system_admin`, `security_auditor`);
- `AuthorizationService`: roles, effective permission codes (union, dedup, active-only), `has_permission`, idempotent `assign_role`/`remove_role`;
- dynamic `super_admin` expansion with no username/id bypass;
- `/auth/me` extended with `roles` and `permissions` (display data);
- frontend `/auth/me` contract adaptation only (no admin UI);
- no management HTTP APIs and no permission-cache in this phase.

Primary tests: role lifecycle, sync idempotence/staleness, grant idempotence, resolution matrix (single/multiple/disabled/deleted/no-roles), super-admin behavior, CLI commands, migration `0003` isolation, `/auth/me` payload.

## Phase 2B: Authorization Core

**Status: complete**

Delivered:

- `require_permission(...)` FastAPI dependency (`app/modules/rbac/dependencies.py`) built on `AuthorizationService` — no dependency-level role or super-admin rules, no new bypass;
- request-scoped `AuthorizationContext` resolved once per request through `Depends` caching (not a cross-request cache; changes apply on the next request);
- fail-fast catalog validation: unknown permission codes raise `ValueError` at dependency-construction time, plus `Permissions` constants so business code never scatters string literals;
- strict 401/403 separation (authentication errors are never rewritten into 403);
- 15-case integration matrix + immediate-effect cycles over a test-only protected router;
- frontend `auth.hasPermission(code)` getter (UX only, documented as not a security boundary);
- no migration — Phase 2B requires no schema change.

## Phase 2C: System Management API

**Status: complete**

Delivered:

- User Management API (`/api/v1/users`): paginated list with keyword/status/department filters, detail with primary department/position summaries, create as employee identity (no credential fields accepted), allowlist PATCH, disable/enable/resign lifecycle with operator self-lockout protection (409 on disabling/resigning yourself, including via PATCH);
- Department Management API (`/api/v1/departments`): list/tree/detail/create/update/move/disable/enable; move reuses Phase 1A cycle prevention (self-parent and descendant targets rejected with 422);
- Position Management API (`/api/v1/positions`): list/detail/create/update/disable/enable; position operations never touch roles or permissions;
- Role Management API (`/api/v1/roles`): list/detail/create/update/disable/enable; `code` and `is_system` are immutable through the API; system roles reject disable;
- Permission Read API (`/api/v1/permissions`): read-only catalog browsing with module/kind/status/keyword filters; no mutation endpoints exist;
- Role-Permission assignment (`GET/PUT /roles/{role_id}/permissions`): whole-set replacement semantics returning added/removed/unchanged report in one transaction; unknown or disabled codes rejected with 422; `super_admin` rejects explicit authorization with 409 (its powers are dynamic expansion);
- User-Role assignment (`GET /users/{user_id}/roles`, `POST/DELETE /users/{user_id}/roles/{role_id}`): idempotent grant/remove, `assigned_by` always the authenticated operator, disabled roles rejected with 409;
- all 34 protected endpoints gated by `require_permission(...)` with catalog constants; permission enforcement is action-level only (no row-level data scope yet);
- no permission cache: authorization changes take effect on the next request;
- no new migration: Phase 2C is pure API/service composition over existing tables.

Primary tests:

- 146 new integration tests (268 total): parameterized unauthenticated(401)/denied(403)/super-admin-allowed matrix over every endpoint group;
- duplicate username/employee_no/role code (including soft-deleted) conflicts;
- self-disable/self-resign/self-PATCH-lockout rejection;
- disable/resign immediately blocks the next authentication request;
- password fields absent from create schema and responses; credential creation impossible through the user API;
- department self-parent/descendant move rejection, CTE tree shape, disable hides from tree;
- role code immutability, system-role protection, disabled-role assignment rejection;
- replacement report add/remove/unchanged semantics, idempotent re-submission;
- permission changes (grant, remove, role-permission edit) reflected in `/auth/me` on the very next request.

## Phase 3A: Workspace And Menu Persistence

**Status: complete**

Delivered:

- code-owned `Workspace Registry` (`app/modules/workspaces/registry.py`) with 8 canonical codes (`operation`, `product`, `procurement`, `warehouse`, `customer-service`, `finance`, `hr`, `tech`) matching the frontend placeholder directories; `purchase` was renamed to `procurement` as the single canonical term; grammar/duplicate validation with registry-level unit tests;
- workspace access permissions derived deterministically from the registry (`workspace:<code>:access`, kind `workspace`, module `workspace`) and merged into the permission catalog — one access code per workspace, no duplicates, `sync-permissions` writes them, and no system role receives them automatically;
- `sync-workspaces` CLI (explicit operator action, `--dry-run`, create/update/unchanged/stale-disable reporting; never deletes, never re-enables operator-disabled rows, refuses codes occupied by soft-deleted rows);
- migration `0004_workspace_menu_foundation` creating `workspaces`, `workspace_departments` (pure many-to-many, composite PK, deliberately no `is_default` — no product consumer), and `menus` (adjacency list, `directory`/`page` only, workspace-relative `route_path`, stable `component_key` contract, optional `permission_code`);
- `WorkspaceService` (lifecycle + association invariants, no create path — registry sync is the only writer), `WorkspaceRegistryService`, and `MenuService` (tree safety: self-parent, descendant cycles via recursive CTE, cross-workspace parents; catalog validation: unknown/disabled `permission_code` rejected; navigation metadata validation);
- schema parity test proving the Alembic path and `Base.metadata` produce identical constraint/index/column sets for the three new tables.

Explicit exclusions (Phase 3B+): `require_workspace_access(...)`, `/auth/workspaces`, `/auth/menus`, any workspace/menu management API, dynamic navigation, frontend dynamic router, navigation caching, data-scope enforcement.

Primary tests:

- registry validation, duplicate codes, frontend-directory parity, System-Management-never-a-workspace guard;
- sync create/idempotent/stale-disable/code-immutable/soft-deleted-code-conflict behavior against real PostgreSQL;
- many-to-many associations in both directions, duplicate rejection, deleted-reference rejection, and proof that associations produce zero role/permission side effects;
- menu create/tree, cross-workspace parent rejection, self-parent and descendant-cycle rejection (recursive CTE), duplicate code per workspace, same code across workspaces, disable/soft-delete/code retirement, sort stability, unknown/disabled/known `permission_code` handling;
- migration cycle `upgrade head → downgrade 0003 → upgrade head` and `downgrade base → upgrade head` with Phase 1/2 schema preservation assertions.

## Phase 3B: Workspace Access & Dynamic Navigation API

**Status: next**

Goals:

- implement `require_workspace_access(...)` wiring `workspace:<code>:access` into authentication + authorization;
- implement `GET /auth/workspaces` and workspace-filtered `GET /auth/menus`;
- implement permission-filtered menu tree composition;
- define the navigation bootstrap contract and cache/invalidation policy.

Primary tests:

- no workspace permission yields no workspace/menu;
- menu visibility does not grant backend access;
- inactive/deleted menus disappear from navigation;
- workspace isolation is enforced.

## Phase 4: Portal And Announcements

Goals:

- implement welcome/my-workspaces portal APIs;
- implement announcement draft/publish/withdraw lifecycle;
- implement audience scope by company/department/role/user;
- implement pinned, scheduled, and expired announcements;
- implement content sanitization policy;
- implement quick links if product requires them.

Primary tests:

- draft not visible;
- withdrawn no longer visible;
- expired excluded;
- audience membership and publication-time history;
- unsafe content policy.

## Phase 5: Audit And Security Hardening

Goals:

- implement sensitive operation audit middleware/service integration;
- implement audit query/export permission model;
- harden token/session revocation;
- add production logging/masking;
- add security regression suite;
- define retention/backup/recovery policy.

Primary tests:

- all sensitive operations produce evidence;
- sensitive values are masked;
- audit API requires explicit permission;
- revoked sessions cannot perform sensitive actions.

## Phase 6: First Business Workspace

Select one bounded pilot workspace, likely Operation Center. The pilot must add:

```text
modules/<business_module>/
```

without modifying core RBAC semantics.

Requirements:

- workspace permission code;
- business permission catalog;
- data-scope column contract;
- module service/repository tests;
- workspace menus;
- business audit events.

The purpose is to validate the platform boundary, not to deliver every business center at once.

## Later Capability Tracks

These remain outside the current phases:

- external marketplace/ERP/WMS integrations;
- workflow/approval engine;
- AI assistant, automation, RAG, and analytics;
- mobile-specific APIs;
- plugin marketplace;
- multi-company/tenant evolution if organizational scope changes.

Each track starts with a design document, permission model, data ownership boundary, and migration/security review before implementation.

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

**Status: current**

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

## Phase 1A: Organization And Identity Data Foundation

**Status: next**

Goals:

- create initial database migrations;
- implement Department model, repository, service, schemas, and admin APIs when ready;
- implement Position model and assignment relationships;
- implement User model with no physical delete;
- implement user-department relationships with a current primary assignment;
- implement user-position relationships;
- implement first-level/recursive department tree reads with PostgreSQL CTEs;
- provide migration, repository/service/schema, and test coverage.

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

## Phase 1B: Authentication

Goals:

- implement password hashing;
- implement local login;
- implement short-lived access tokens;
- implement refresh token as `HttpOnly`, `Secure`, `SameSite` cookie;
- implement refresh-token rotation and reuse detection;
- implement logout and cookie clearing;
- implement current-user endpoint;
- validate active/disabled/resigned account state before authorization;
- implement login logs;
- implement username/account/IP brute-force protection.

Primary tests:

- authentication success/failure;
- expired/revoked/reused refresh token;
- refresh cookie is HttpOnly, Secure, SameSite, and never exposed in JSON;
- disabled/resigned account cannot authenticate or retain access;
- logout revokes the token family;
- brute-force lockout/throttling.

## Phase 2: Roles, Permissions, And RBAC

Goals:

- implement roles, permissions, role permissions, and user roles;
- implement permission code catalog/seed;
- implement reusable backend permission dependencies;
- implement role administration and audit;
- enforce no direct user-permission assignment.

Primary tests:

- RBAC permission matrix;
- role disable/remove;
- sensitive change audit;
- separation of position and role.

## Phase 3: Workspaces, Menus, And Dynamic Navigation

Goals:

- implement first-class workspaces;
- implement workspace/department associations;
- implement workspace menus;
- implement authenticated workspace/menu APIs;
- implement workspace permission dependencies;
- define navigation cache and invalidation policy.

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

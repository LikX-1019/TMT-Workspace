# Roadmap

## Phase 0: Architecture And Repository Bootstrap

**Status: current**

Goals:

- establish modular monolith architecture;
- establish FastAPI/SQLAlchemy conventions;
- establish configuration, health API, response/error contracts;
- prepare async Alembic foundation;
- establish security-first RBAC/data-scope design;
- establish AI coding and validation rules.

Exit criteria:

- repository runs;
- `make check` passes;
- architecture and platform policies are documented;
- future phases can proceed without redesigning module boundaries.

## Phase 1: Authentication, User, And Department

Goals:

- create initial database migrations;
- implement password hashing;
- implement local login, refresh, logout;
- implement access-token dependency and account-state checks;
- implement user CRUD with no physical delete;
- implement department tree and closure maintenance;
- implement login logs and basic brute-force throttling;
- bootstrap initial system administrator.

Primary tests:

- authentication success/failure;
- expired/revoked token;
- disabled/resigned account;
- duplicate username/email/employee number;
- department cycle prevention;
- department move/closure integrity.

## Phase 2: Positions, Roles, Permissions, And RBAC

Goals:

- implement positions and assignments;
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

